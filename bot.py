# bot.py — screamsoon casino
import asyncio
import functools
import html
import json
import os
import random
import re
import time
from typing import Optional, Union

from dotenv import load_dotenv

load_dotenv()

# ============ КОНФИГУРАЦИЯ ИЗ .ENV ============

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "screamsoon").lstrip("@")
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "screamsoonlarp").strip()
REQUIRED_CHANNEL_ID = int(os.getenv("REQUIRED_CHANNEL_ID", "0"))

DAILY_BONUS = int(os.getenv("DAILY_BONUS", "1000"))
SUBSCRIBE_REWARD = int(os.getenv("SUBSCRIBE_REWARD", "500"))
START_BALANCE = int(os.getenv("START_BALANCE", "0"))
MINES_COUNT = int(os.getenv("MINES_COUNT", "5"))

DB_BACKEND = os.getenv("DB_BACKEND", "postgres").lower()
DB_PATH = os.getenv("DB_PATH", "screamsoon.db")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

CURRENCY = "scream"

# ============ ПРЕМИУМ ЭМОДЗИ TELEGRAM ============
PREMIUM_EMOJIS = {
    "casino":   "5431536464246634160",  # 🎰 Главный значок казика
    "fire":     "5188487846968732572",  # 🔥 Огонь / статус Профи
    "money":    "5240290577102152084",  # 💸 Деньги / переводы / выигрыши
    "bag":      "5359785904535774578",  # 💼 Баланс / портфель
    "gem":      "5427168083074628963",  # 💎 Алмаз / кристалл в минах
    "boom":     "5469785308386041323",  # 💥 Взрыв мины
    "bomb":     "5370692462882857093",  # 💣 Мины
    "skull":    "5370598007962083530",  # 💀 Череп в джокере / лузер
    "joker":    "5221929570436925455",  # 🃏 Карта джокера
    "trophy":   "5409008750893734809",  # 🏆 Кубок / полная победа
    "crown":    "5210952531676516344",  # 👑 Корона / статус Легенда
    "gift":     "5199749070830197566",  # 🎁 Кейсы и ежедневный бонус
    "dice":     "5310180170433327723",  # 🎲 Игральные кости
    "chart_up": "5373001317042101552",  # 📈 Профит в плюс / рост множителя
    "chart_dn": "5361748661640372834",  # 📉 Профит в минус
    "stop":     "5240241223632954241",  # 🚫 Ограничение / предупреждение
    "check":    "6327717992268301521",  # ✅ Успешное действие / проверка
    "hour":     "5370561264516865667",  # ⏳ Таймер бонуса
    "target":   "5323772968831052011",  # 🎯 Ставка
    "cool":     "5242588152677282638",  # 😏 Смайлик подколки
    "greedy":   "5242679150149383215",  # 🤑 Жадный смайлик с долларами
    "chick":    "5470113903448956707",  # 🐣 Статус Новичок
    "player":   "5235588635885054955",  # 🎲 Статус Игрок
}


def e(key: str, fallback: str) -> str:
    """Генерирует HTML-тег для премиум-эмодзи Телеграма."""
    custom_id = PREMIUM_EMOJIS.get(key, "").strip()
    if custom_id:
        return f'<tg-emoji id="{custom_id}">{fallback}</tg-emoji>'
    return fallback


if not BOT_TOKEN:
    raise SystemExit("Ошибка: BOT_TOKEN не задан в .env файле!")

# ================================================

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

Event = Union[Message, CallbackQuery]

# ==================== БАЗА ДАННЫХ ====================

import aiosqlite

try:
    import asyncpg
    HAS_PG = True
except ImportError:
    HAS_PG = False

_pg_pool: Optional["asyncpg.Pool"] = None


def _is_pg() -> bool:
    return DB_BACKEND == "postgres"


def _strip_url(url: str) -> str:
    if "+asyncpg" in url:
        url = url.replace("postgresql+asyncpg://", "postgresql://")
    if "?" in url:
        url = url.split("?", 1)[0]
    return url


async def _pg_init_pool():
    global _pg_pool
    if not HAS_PG:
        raise SystemExit("Установлен DB_BACKEND=postgres, но библиотека asyncpg не установлена!")
    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL не задан в .env файле!")

    clean_url = _strip_url(DATABASE_URL)
    _pg_pool = await asyncpg.create_pool(
        clean_url,
        min_size=1,
        max_size=10,
        ssl=False,  # Отключаем SSL для серверов без ssl upgrade
        command_timeout=30,
    )
    print("[БД] Успешное подключение к PostgreSQL!")


def _pg_conn():
    return _pg_pool.acquire()


def _convert_qmarks(sql: str) -> str:
    out, idx = [], 0
    for ch in sql:
        if ch == "?":
            idx += 1
            out.append(f"${idx}")
        else:
            out.append(ch)
    return "".join(out)


async def _q(sql: str, *args) -> list:
    if _is_pg():
        sql_pg = _convert_qmarks(sql)
        async with _pg_conn() as conn:
            rows = await conn.fetch(sql_pg, *args)
            return [dict(r) for r in rows]
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, args) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]


async def _x(sql: str, *args) -> None:
    if _is_pg():
        sql_pg = _convert_qmarks(sql)
        async with _pg_conn() as conn:
            await conn.execute(sql_pg, *args)
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(sql, args)
            await db.commit()


# ==================== ТАБЛИЦЫ ====================

SQLITE_SCHEMA_USERS = """
    CREATE TABLE IF NOT EXISTS users (
        user_id      INTEGER PRIMARY KEY,
        username     TEXT,
        first_name   TEXT,
        balance      INTEGER DEFAULT 0,
        last_bonus   INTEGER DEFAULT 0,
        sub_rewarded INTEGER DEFAULT 0,
        total_bet    INTEGER DEFAULT 0,
        total_won    INTEGER DEFAULT 0,
        games_played INTEGER DEFAULT 0,
        games_won    INTEGER DEFAULT 0,
        max_win      INTEGER DEFAULT 0,
        created_at   INTEGER DEFAULT (strftime('%s','now'))
    )
"""

SQLITE_SCHEMA_GAMES = """
    CREATE TABLE IF NOT EXISTS active_games (
        user_id    INTEGER PRIMARY KEY,
        game       TEXT,
        bet        INTEGER,
        state      TEXT,
        created_at INTEGER
    )
"""

PG_SCHEMA_USERS = """
    CREATE TABLE IF NOT EXISTS users (
        user_id      BIGINT PRIMARY KEY,
        username     TEXT,
        first_name   TEXT,
        balance      BIGINT DEFAULT 0,
        last_bonus   BIGINT DEFAULT 0,
        sub_rewarded INTEGER DEFAULT 0,
        total_bet    BIGINT DEFAULT 0,
        total_won    BIGINT DEFAULT 0,
        games_played BIGINT DEFAULT 0,
        games_won    BIGINT DEFAULT 0,
        max_win      BIGINT DEFAULT 0,
        created_at   BIGINT DEFAULT EXTRACT(EPOCH FROM NOW())::BIGINT
    )
"""

PG_SCHEMA_GAMES = """
    CREATE TABLE IF NOT EXISTS active_games (
        user_id    BIGINT PRIMARY KEY,
        game       TEXT,
        bet        BIGINT,
        state      TEXT,
        created_at BIGINT
    )
"""


async def init_db():
    if _is_pg():
        await _pg_init_pool()
        async with _pg_conn() as conn:
            await conn.execute(PG_SCHEMA_USERS)
            await conn.execute(PG_SCHEMA_GAMES)

        rows = await _q(
            "SELECT column_name FROM information_schema.columns WHERE table_name='users'"
        )
        existing = {r["column_name"] for r in rows}
        needed = {
            "username":     "TEXT",
            "first_name":   "TEXT",
            "balance":      "BIGINT DEFAULT 0",
            "last_bonus":   "BIGINT DEFAULT 0",
            "sub_rewarded": "INTEGER DEFAULT 0",
            "total_bet":    "BIGINT DEFAULT 0",
            "total_won":    "BIGINT DEFAULT 0",
            "games_played": "BIGINT DEFAULT 0",
            "games_won":    "BIGINT DEFAULT 0",
            "max_win":      "BIGINT DEFAULT 0",
            "created_at":   "BIGINT",
        }
        async with _pg_conn() as conn:
            for col, decl in needed.items():
                if col not in existing:
                    await conn.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(SQLITE_SCHEMA_USERS)
            await db.execute(SQLITE_SCHEMA_GAMES)
            await db.commit()

            async with db.execute("PRAGMA table_info(users)") as cur:
                existing = {row[1] for row in await cur.fetchall()}
            needed = {
                "username":     "TEXT",
                "first_name":   "TEXT",
                "balance":      "INTEGER DEFAULT 0",
                "last_bonus":   "INTEGER DEFAULT 0",
                "sub_rewarded": "INTEGER DEFAULT 0",
                "total_bet":    "INTEGER DEFAULT 0",
                "total_won":    "INTEGER DEFAULT 0",
                "games_played": "INTEGER DEFAULT 0",
                "games_won":    "INTEGER DEFAULT 0",
                "max_win":      "INTEGER DEFAULT 0",
                "created_at":   "INTEGER",
            }
            for col, decl in needed.items():
                if col not in existing:
                    await db.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
            await db.commit()


# ==================== ОПЕРАЦИИ БАЗЫ ====================

async def get_user(user_id: int, username: Optional[str] = None,
                   first_name: Optional[str] = None) -> dict:
    rows = await _q("SELECT * FROM users WHERE user_id=?", user_id)
    if not rows:
        await _x(
            "INSERT INTO users (user_id, username, first_name, balance) VALUES (?,?,?,?)",
            user_id, username, first_name, START_BALANCE,
        )
    else:
        row = rows[0]
        updates, params = [], []
        if username and row.get("username") != username:
            updates.append("username=?"); params.append(username)
        if first_name and row.get("first_name") != first_name:
            updates.append("first_name=?"); params.append(first_name)
        if updates:
            params.append(user_id)
            await _x(f"UPDATE users SET {', '.join(updates)} WHERE user_id=?", *params)
    rows = await _q("SELECT * FROM users WHERE user_id=?", user_id)
    return rows[0]


async def add_balance(user_id: int, amount: int) -> None:
    await _x("UPDATE users SET balance = balance + ? WHERE user_id=?", amount, user_id)


async def try_deduct_balance(user_id: int, amount: int) -> bool:
    if amount <= 0:
        return True
    if _is_pg():
        async with _pg_conn() as conn:
            res = await conn.execute(
                "UPDATE users SET balance = balance - $1 WHERE user_id = $2 AND balance >= $1",
                amount, user_id,
            )
            return res == "UPDATE 1"
    else:
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                (amount, user_id, amount),
            )
            await db.commit()
            return cur.rowcount > 0


async def set_balance(user_id: int, amount: int) -> None:
    await _x("UPDATE users SET balance=? WHERE user_id=?", amount, user_id)


async def set_bonus_time(user_id: int, ts: int) -> None:
    await _x("UPDATE users SET last_bonus=? WHERE user_id=?", ts, user_id)


async def mark_sub_rewarded(user_id: int) -> None:
    await _x("UPDATE users SET sub_rewarded=1 WHERE user_id=?", user_id)


async def stat_bet(user_id: int, bet: int) -> None:
    await _x(
        "UPDATE users SET total_bet=total_bet+?, games_played=games_played+1 WHERE user_id=?",
        bet, user_id,
    )


async def stat_win(user_id: int, profit: int) -> None:
    if _is_pg():
        await _x(
            "UPDATE users SET total_won=total_won+?, games_won=games_won+1, "
            "max_win = GREATEST(max_win, ?) WHERE user_id=?",
            profit, profit, user_id,
        )
    else:
        await _x(
            "UPDATE users SET total_won=total_won+?, games_won=games_won+1, "
            "max_win = MAX(max_win, ?) WHERE user_id=?",
            profit, profit, user_id,
        )


async def save_game(user_id: int, game: str, bet: int, state: dict) -> None:
    if _is_pg():
        await _x(
            """INSERT INTO active_games (user_id, game, bet, state, created_at)
               VALUES (?,?,?,?, EXTRACT(EPOCH FROM NOW())::BIGINT)
               ON CONFLICT (user_id) DO UPDATE SET
                 game=EXCLUDED.game, bet=EXCLUDED.bet,
                 state=EXCLUDED.state, created_at=EXCLUDED.created_at""",
            user_id, game, bet, json.dumps(state),
        )
    else:
        await _x(
            """INSERT INTO active_games (user_id, game, bet, state, created_at)
               VALUES (?,?,?,?, strftime('%s','now'))
               ON CONFLICT(user_id) DO UPDATE SET
                 game=excluded.game, bet=excluded.bet,
                 state=excluded.state, created_at=excluded.created_at""",
            user_id, game, bet, json.dumps(state),
        )


async def get_game(user_id: int) -> Optional[dict]:
    rows = await _q("SELECT * FROM active_games WHERE user_id=?", user_id)
    if not rows:
        return None
    g = rows[0]
    now = int(time.time())
    if now - g.get("created_at", 0) > 900:
        await delete_game(user_id)
        return None
    g["state"] = json.loads(g["state"])
    return g


async def delete_game(user_id: int) -> None:
    await _x("DELETE FROM active_games WHERE user_id=?", user_id)


async def find_user_by_username(username: str) -> Optional[dict]:
    rows = await _q("SELECT * FROM users WHERE username=?", username)
    return rows[0] if rows else None


async def give_all(amount: int) -> int:
    await _x("UPDATE users SET balance = balance + ?", amount)
    rows = await _q("SELECT COUNT(*) AS n FROM users")
    return rows[0]["n"]


# ==================== ОФОРМЛЕНИЕ И UI ====================

def fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def progress_bar(cur: int, total: int, length: int = 10) -> str:
    if total <= 0:
        return "░" * length
    filled = max(0, min(length, round(cur / total * length)))
    return "▓" * filled + "░" * (length - filled)


def user_title(games: int, won: int) -> str:
    if games < 5:
        return f"{e('chick', '🐣')} Новичок"
    wr = won / games * 100
    if wr < 25:
        return f"{e('skull', '💀')} Лузер"
    if wr < 40:
        return f"{e('player', '🎲')} Игрок"
    if wr < 55:
        return f"{e('casino', '🎰')} Крутой"
    if wr < 70:
        return f"{e('fire', '🔥')} Профи"
    return f"{e('crown', '👑')} Легенда"


def home_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="🏠 Меню", callback_data="menu:home")


async def show(event: Event, text: str, kb: InlineKeyboardMarkup,
               edit: bool = True) -> None:
    if isinstance(event, CallbackQuery):
        if edit:
            try:
                await event.message.edit_text(text, reply_markup=kb)
                return
            except Exception:
                pass
        await event.message.answer(
            text, reply_markup=kb,
            reply_to_message_id=event.message.message_id,
        )
    else:
        await event.answer(text, reply_markup=kb)


async def show_alert(event: CallbackQuery, text: str) -> None:
    await event.answer(text, show_alert=True)


# ==================== ПОДПИСКА ====================

def get_channel_handle() -> str:
    return REQUIRED_CHANNEL.replace("https://t.me/", "").replace("t.me/", "").lstrip("@").strip()


async def is_subscribed(user_id: int) -> bool:
    if not REQUIRED_CHANNEL_ID:
        return True
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return True


def sub_keyboard() -> InlineKeyboardMarkup:
    handle = get_channel_handle()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"📢 Подписаться на @{handle}",
            url=f"https://t.me/{handle}",
        )],
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="check_sub")],
    ])


async def gate(event: Event) -> bool:
    if await is_subscribed(event.from_user.id):
        return True
    handle = get_channel_handle()
    text = (
        f"{e('stop', '🚫')} <b>Э, стоять!</b>\n\n"
        f"Без подписки на @{handle} казино <b>screamsoon</b> закрыто.\n"
        f"Подпишись — и сразу получи <b>+{fmt(SUBSCRIBE_REWARD)} {CURRENCY}</b> на баланс! {e('money', '💸')}"
    )
    await show(event, text, sub_keyboard(), edit=False)
    return False


# ==================== ГЛАВНОЕ МЕНЮ ====================

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Мины", callback_data="menu:mines"),
         InlineKeyboardButton(text="🃏 Джокер", callback_data="menu:joker")],
        [InlineKeyboardButton(text="🎲 Кости (PvE)", callback_data="menu:dice"),
         InlineKeyboardButton(text="🎁 Кейсы", callback_data="menu:cases")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="menu:profile"),
         InlineKeyboardButton(text="🎁 Бонус", callback_data="menu:bonus")],
        [InlineKeyboardButton(text="💸 Перевод", callback_data="menu:pay"),
         InlineKeyboardButton(text="💎 Купить scream", callback_data="menu:buy")],
    ])


async def render_menu(event: Event, edit: bool = True) -> None:
    u = await get_user(event.from_user.id, event.from_user.username,
                       event.from_user.first_name)
    cas = e('casino', '🎰')
    text = (
        f"{cas} <b>SCREAMSOON CASINO</b> {cas}\n"
        f"└ где твои деньги плачут, а @{ADMIN_USERNAME} кайфует {e('cool', '😏')}\n\n"
        f"👤 <b>{html.escape(event.from_user.first_name or 'anon')}</b> "
        f"[{user_title(u['games_played'], u['games_won'])}]\n"
        f"{e('bag', '💼')} Баланс: <b>{fmt(u['balance'])} {CURRENCY}</b>\n\n"
        f"👇 Выбирай режим:"
    )
    await show(event, text, main_menu_kb(), edit=edit)


# ==================== ИГРА 1: МИНЫ ====================

MINES_GRID = 5
MINES_TOTAL = MINES_GRID * MINES_GRID


def mines_new_state(mines_count: int, bet: int) -> dict:
    cells = random.sample(range(MINES_TOTAL), mines_count)
    return {"mines": sorted(cells), "opened": [],
            "mines_count": mines_count, "bet": bet}


def mines_multiplier(mines_count: int, opened: int) -> float:
    if opened == 0:
        return 1.0
    safe_total = MINES_TOTAL - mines_count
    m = 1.0
    for i in range(opened):
        m *= (MINES_TOTAL - i) / (safe_total - i)
    return round(m * 0.97, 3)


def mines_kb(uid: int, state: dict, game_over: bool = False) -> InlineKeyboardMarkup:
    opened = set(state["opened"])
    mines = set(state["mines"])
    rows = []
    for r in range(MINES_GRID):
        row = []
        for c in range(MINES_GRID):
            idx = r * MINES_GRID + c
            if idx in mines and game_over:
                btn_txt = "💥"
            elif idx in opened or game_over:
                btn_txt = "💎"
            else:
                btn_txt = "⬜"
            row.append(InlineKeyboardButton(text=btn_txt, callback_data=f"mine:{uid}:{idx}"))
        rows.append(row)
    if not game_over and state["opened"]:
        mult = mines_multiplier(state["mines_count"], len(opened))
        pot = int(state["bet"] * mult)
        rows.append([InlineKeyboardButton(
            text=f"💰 ЗАБРАТЬ {fmt(pot)} {CURRENCY}", callback_data=f"mine:{uid}:cashout")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mines_text(state: dict, result: Optional[str] = None) -> str:
    n = len(state["opened"])
    mult = mines_multiplier(state["mines_count"], n)
    pot = int(state["bet"] * mult)
    lines = [
        f"{e('bomb', '💣')} <b>МИНЫ (SCREAMSOON)</b>",
        f"💥 Мин на поле: <b>{state['mines_count']}</b>",
        f"{e('target', '🎯')} Ставка: <b>{fmt(state['bet'])} {CURRENCY}</b>",
        f"{e('gem', '💎')} Открыто: <b>{n}</b>",
        f"{e('chart_up', '📈')} Множитель: <b>x{mult}</b>",
        f"💰 Заберёшь: <b>{fmt(pot)} {CURRENCY}</b>",
    ]
    if result:
        lines += ["", result]
    return "\n".join(lines)


# ==================== ИГРА 2: ДЖОКЕР ====================

JOKER_COLS = 3
JOKER_HOUSE_EDGE = 0.97


def joker_new_round() -> dict:
    return {"skull": random.randint(0, JOKER_COLS - 1)}


def joker_new_state(bet: int) -> dict:
    return {
        "bet": bet,
        "rounds": [],
        "current": joker_new_round(),
        "current_opened": None,
    }


def joker_multiplier(rounds_passed: int) -> float:
    if rounds_passed == 0:
        return 1.0
    m = (3 / 2) ** rounds_passed
    return round(m * JOKER_HOUSE_EDGE, 2)


def joker_kb(uid: int, state: dict, game_over: bool = False) -> InlineKeyboardMarkup:
    rows = []
    for r in state["rounds"]:
        skull = r["skull"]
        opened_safe = r.get("opened_safe")
        row = []
        for i in range(JOKER_COLS):
            if i == skull:
                txt = "💀"
            elif game_over or i == opened_safe:
                txt = "🃏"
            else:
                txt = "🂠"
            row.append(InlineKeyboardButton(text=txt, callback_data=f"jok:{uid}:nothing"))
        rows.append(row)

    if not game_over:
        opened = state.get("current_opened")
        row = []
        for i in range(JOKER_COLS):
            txt = "🃏" if i == opened else "🂠"
            row.append(InlineKeyboardButton(text=txt, callback_data=f"jok:{uid}:{i}"))
        rows.append(row)
    elif state.get("current") is not None:
        cur_skull = state["current"]["skull"]
        row = []
        for i in range(JOKER_COLS):
            txt = "💀" if i == cur_skull else "🃏"
            row.append(InlineKeyboardButton(text=txt, callback_data=f"jok:{uid}:nothing"))
        rows.append(row)

    rounds_passed = len(state["rounds"])
    if not game_over and rounds_passed > 0:
        mult = joker_multiplier(rounds_passed)
        pot = int(state["bet"] * mult)
        rows.append([InlineKeyboardButton(
            text=f"💰 ЗАБРАТЬ {fmt(pot)} {CURRENCY} (x{mult})",
            callback_data=f"jok:{uid}:cashout")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def joker_text(state: dict, game_over: bool = False,
               result: Optional[str] = None) -> str:
    rounds_passed = len(state["rounds"])
    mult = joker_multiplier(rounds_passed)
    pot = int(state["bet"] * mult)
    lines = [
        f"{e('joker', '🃏')} <b>ДЖОКЕР (SCREAMSOON)</b>",
        f"{e('target', '🎯')} Ставка: <b>{fmt(state['bet'])} {CURRENCY}</b>",
        f"🏁 Пройдено строк: <b>{rounds_passed}</b>",
        f"{e('chart_up', '📈')} Множитель: <b>x{mult}</b>",
        f"💰 Заберёшь: <b>{fmt(pot)} {CURRENCY}</b>",
    ]
    if result:
        lines += ["", result]
    return "\n".join(lines)


# ==================== КЕЙСЫ ====================

CASES = {
    "bronze": {
        "name": "🥉 Бронза", "price": 500,
        "items": [("0", 350), ("100", 250), ("300", 200),
                  ("600", 130), ("1500", 50), ("5000", 18), ("25000", 2)],
    },
    "silver": {
        "name": "🥈 Серебро", "price": 2500,
        "items": [("0", 350), ("500", 220), ("1500", 200),
                  ("3000", 150), ("7500", 60), ("25000", 15), ("100000", 5)],
    },
    "gold": {
        "name": "🥇 Золото", "price": 10000,
        "items": [("0", 420), ("2500", 220), ("7500", 180),
                  ("15000", 120), ("40000", 45), ("120000", 10), ("500000", 5)],
    },
}

CASE_ALIASES = {
    "бронза": "bronze", "бронз": "bronze", "bronze": "bronze",
    "серебро": "silver", "серебр": "silver", "silver": "silver",
    "золото": "gold", "золот": "gold", "gold": "gold",
}


def open_case(key: str) -> int:
    c = CASES[key]
    pop = [i[0] for i in c["items"]]
    w = [i[1] for i in c["items"]]
    return int(random.choices(pop, weights=w, k=1)[0])


def cases_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text=f"{c['name']} — {fmt(c['price'])} {CURRENCY}", callback_data=f"case:{k}")]
        for k, c in CASES.items()]
    rows.append([home_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ==================== ПРОФИЛЬ ====================

def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[home_button()]])


def buy_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"✍️ Написать @{ADMIN_USERNAME}",
            url=f"https://t.me/{ADMIN_USERNAME}")],
        [home_button()],
    ])


def profile_text(u: dict, name: str) -> str:
    games = u["games_played"]
    won = u["games_won"]
    wr = (won / games * 100) if games else 0
    net = u["total_won"] - u["total_bet"]
    net_icon = e('chart_up', '📈') if net >= 0 else e('chart_dn', '📉')
    return (
        f"👤 <b>Профиль</b> — {html.escape(name)}\n"
        f"└ {user_title(games, won)}\n\n"
        f"{e('bag', '💼')} Баланс: <b>{fmt(u['balance'])} {CURRENCY}</b>\n\n"
        f"🎮 Игр сыграно: <b>{games}</b>\n"
        f"{e('trophy', '🏆')} Побед: <b>{won}</b>\n"
        f"📊 Винрейт: <b>{wr:.1f}%</b>\n"
        f"{progress_bar(won, games)}\n\n"
        f"{e('money', '💸')} Всего поставлено: <b>{fmt(u['total_bet'])} {CURRENCY}</b>\n"
        f"💰 Всего выиграно: <b>{fmt(u['total_won'])} {CURRENCY}</b>\n"
        f"🏅 Макс. выигрыш: <b>{fmt(u['max_win'])} {CURRENCY}</b>\n"
        f"{net_icon} Чистый профит: <b>{'+' if net >= 0 else ''}{fmt(net)} {CURRENCY}</b>"
    )


# ==================== ХЕНДЛЕРЫ МЕНЮ ====================

@dp.message(Command("start"))
async def cmd_start(m: Message):
    if not await gate(m):
        return
    await get_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    await render_menu(m, edit=False)


@dp.callback_query(F.data == "menu:home")
async def cb_home(cq: CallbackQuery):
    if not await gate(cq):
        return
    await render_menu(cq, edit=True)
    await cq.answer()


@dp.callback_query(F.data == "menu:profile")
async def cb_profile(cq: CallbackQuery):
    if not await gate(cq):
        return
    u = await get_user(cq.from_user.id, cq.from_user.username, cq.from_user.first_name)
    await show(cq, profile_text(u, cq.from_user.first_name or "anon"), profile_kb())
    await cq.answer()


@dp.callback_query(F.data == "menu:bonus")
async def cb_bonus(cq: CallbackQuery):
    if not await gate(cq):
        return
    u = await get_user(cq.from_user.id, cq.from_user.username, cq.from_user.first_name)
    now = int(time.time())
    if now - u["last_bonus"] < 86400:
        left = 86400 - (now - u["last_bonus"])
        h, rem = divmod(left, 3600)
        await show(cq, f"{e('hour', '⏳')} <b>Бонус ещё не готов</b>\n\n└ Жди <b>{h}ч {rem // 60}м</b>",
                   profile_kb())
        await cq.answer("Рано!")
        return
    await add_balance(cq.from_user.id, DAILY_BONUS)
    await set_bonus_time(cq.from_user.id, now)
    await show(cq, f"{e('gift', '🎁')} <b>+{fmt(DAILY_BONUS)} {CURRENCY}</b>\n└ Не слей всё сразу {e('cool', '😏')}",
               profile_kb())
    await cq.answer(f"+{DAILY_BONUS} {CURRENCY}")


@dp.callback_query(F.data == "menu:pay")
async def cb_pay(cq: CallbackQuery):
    if not await gate(cq):
        return
    await show(cq,
        f"{e('money', '💸')} <b>Перевод {CURRENCY}</b>\n\n"
        f"└ В чате: ответь на сообщение игрока и напиши <code>п 500</code>\n"
        f"└ В лс: <code>/pay @ник 500</code>",
        profile_kb())
    await cq.answer()


@dp.callback_query(F.data == "menu:buy")
async def cb_buy(cq: CallbackQuery):
    if not await gate(cq):
        return
    await show(cq,
        f"{e('gem', '💎')} <b>КУПИТЬ {CURRENCY.upper()}</b> {e('gem', '💎')}\n"
        f"└ Официальная валюта казино <b>screamsoon</b>\n\n"
        f"💰 <b>Курс обмена:</b>\n"
        f"└ <b>10 000 {CURRENCY}</b> = <b>10 ₽</b> или <b>10 ⭐</b>\n"
        f"└ <b>50 000 {CURRENCY}</b> = <b>45 ₽</b> или <b>45 ⭐</b>\n"
        f"└ <b>100 000 {CURRENCY}</b> = <b>80 ₽</b> или <b>80 ⭐</b>\n\n"
        f"✍️ Писать лично владельцу: @{ADMIN_USERNAME}\n"
        f"└ Укажи сколько валюты надо и способ оплаты\n\n"
        f"{e('fire', '🔥')} Валюта выдается сразу после подтверждения.",
        buy_kb())
    await cq.answer()


# ==================== ВЫБОР ИГР ====================

@dp.callback_query(F.data == "menu:mines")
async def cb_menu_mines(cq: CallbackQuery):
    if not await gate(cq):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💣 100 {CURRENCY}", callback_data="mines:new:100"),
         InlineKeyboardButton(text=f"💣 500 {CURRENCY}", callback_data="mines:new:500")],
        [InlineKeyboardButton(text=f"💣 1 000 {CURRENCY}", callback_data="mines:new:1000"),
         InlineKeyboardButton(text=f"💣 5 000 {CURRENCY}", callback_data="mines:new:5000")],
        [home_button()],
    ])
    await show(cq,
        f"{e('bomb', '💣')} <b>МИНЫ (SCREAMSOON)</b>\n"
        f"└ 5 мин на поле 5×5\n"
        f"└ Открывай безопасные клетки, расти множитель и вовремя жми ЗАБРАТЬ!\n\n"
        f"👇 Выбери ставку:", kb)
    await cq.answer()


@dp.callback_query(F.data == "menu:joker")
async def cb_menu_joker(cq: CallbackQuery):
    if not await gate(cq):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🃏 100 {CURRENCY}", callback_data="joker:new:100"),
         InlineKeyboardButton(text=f"🃏 500 {CURRENCY}", callback_data="joker:new:500")],
        [InlineKeyboardButton(text=f"🃏 1 000 {CURRENCY}", callback_data="joker:new:1000"),
         InlineKeyboardButton(text=f"🃏 5 000 {CURRENCY}", callback_data="joker:new:5000")],
        [home_button()],
    ])
    await show(cq,
        f"{e('joker', '🃏')} <b>ДЖОКЕР (SCREAMSOON)</b>\n"
        f"└ В каждой строке: 2 карты Джокера и 1 Череп\n"
        f"└ Нашёл Джокера — уровень пройден, куш растёт!\n"
        f"└ Череп — ставка сгорает!\n\n"
        f"👇 Выбери ставку:", kb)
    await cq.answer()


@dp.callback_query(F.data == "menu:dice")
async def cb_menu_dice(cq: CallbackQuery):
    if not await gate(cq):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎲 100 {CURRENCY}", callback_data="dice:new:100"),
         InlineKeyboardButton(text=f"🎲 500 {CURRENCY}", callback_data="dice:new:500")],
        [InlineKeyboardButton(text=f"🎲 1 000 {CURRENCY}", callback_data="dice:new:1000"),
         InlineKeyboardButton(text=f"🎲 5 000 {CURRENCY}", callback_data="dice:new:5000")],
        [home_button()],
    ])
    await show(cq,
        f"{e('dice', '🎲')} <b>КОСТИ (DICE BATTLE)</b>\n"
        f"└ Ты бросаешь кубики против казино screamsoon\n"
        f"└ У кого больше сумма очков — забирает банк (x1.95)!\n\n"
        f"👇 Выбери ставку:", kb)
    await cq.answer()


@dp.callback_query(F.data == "menu:cases")
async def cb_menu_cases(cq: CallbackQuery):
    if not await gate(cq):
        return
    await show(cq,
        f"{e('gift', '🎁')} <b>КЕЙСЫ SCREAMSOON</b>\n"
        f"└ Испытай удачу и забери солидный джекпот!\n\n"
        f"👇 Выбирай кейс:", cases_kb())
    await cq.answer()


# ==================== ХОД ИГРЫ: МИНЫ ====================

@dp.callback_query(F.data.startswith("mines:new:"))
async def cb_mines_new(cq: CallbackQuery):
    if not await gate(cq):
        return
    bet = int(cq.data.split(":")[2])
    ok = await try_deduct_balance(cq.from_user.id, bet)
    if not ok:
        await show_alert(cq, f"❌ Недостаточно {CURRENCY} для ставки {fmt(bet)}!")
        return
    if await get_game(cq.from_user.id):
        await add_balance(cq.from_user.id, bet)
        await show_alert(cq, "У тебя уже идёт активная игра!")
        return

    await stat_bet(cq.from_user.id, bet)
    state = mines_new_state(MINES_COUNT, bet)
    await save_game(cq.from_user.id, "mines", bet, state)
    await show(cq, mines_text(state), mines_kb(cq.from_user.id, state))
    await cq.answer()


@dp.callback_query(F.data.startswith("mine:"))
async def cb_mine(cq: CallbackQuery):
    if not await gate(cq):
        return
    parts = cq.data.split(":")
    owner_id = int(parts[1])
    action = parts[2]

    if cq.from_user.id != owner_id:
        await cq.answer("🚫 Это не твоя игра!", show_alert=True)
        return

    game = await get_game(owner_id)
    if not game or game["game"] != "mines":
        await cq.answer("Нет активной игры.")
        return
    state = game["state"]

    if action == "cashout":
        mult = mines_multiplier(state["mines_count"], len(state["opened"]))
        total = int(game["bet"] * mult)
        profit = total - game["bet"]
        await add_balance(owner_id, total)
        await stat_win(owner_id, profit)
        await delete_game(owner_id)
        result = (f"💰 <b>ЗАБРАЛ {fmt(total)} {CURRENCY}</b> (x{mult})\n"
                  f"└ Чистый профит: <b>+{fmt(profit)} {CURRENCY}</b> {e('greedy', '🤑')}")
        await show(cq, mines_text(state, result), mines_kb(owner_id, state, True))
        await cq.answer("Забрано!")
        return

    idx = int(action)
    if idx in state["opened"]:
        await cq.answer("Уже открыто")
        return

    if idx in state["mines"]:
        await delete_game(owner_id)
        result = (f"{e('boom', '💥')} <b>МИНА!</b> Ты проиграл <b>{fmt(game['bet'])} {CURRENCY}</b>\n"
                  f"└ Казино screamsoon говорит спасибо {e('skull', '💀')}")
        await show(cq, mines_text(state, result), mines_kb(owner_id, state, True))
        await cq.answer("Бум 💥")
        return

    state["opened"].append(idx)
    if len(state["opened"]) == MINES_TOTAL - state["mines_count"]:
        mult = mines_multiplier(state["mines_count"], len(state["opened"]))
        total = int(game["bet"] * mult)
        profit = total - game["bet"]
        await add_balance(owner_id, total)
        await stat_win(owner_id, profit)
        await delete_game(owner_id)
        result = (f"{e('trophy', '🏆')} <b>ВСЁ ПОЛЕ ЗАЧИЩЕНО!</b> Выигрыш <b>{fmt(total)} {CURRENCY}</b> (x{mult})\n"
                  f"└ Ты легенда казика screamsoon! {e('crown', '👑')}")
        await show(cq, mines_text(state, result), mines_kb(owner_id, state, True))
        await cq.answer("Победа 🏆")
        return

    await save_game(owner_id, "mines", game["bet"], state)
    await show(cq, mines_text(state), mines_kb(owner_id, state))
    await cq.answer()


# ==================== ХОД ИГРЫ: ДЖОКЕР ====================

@dp.callback_query(F.data.startswith("joker:new:"))
async def cb_joker_new(cq: CallbackQuery):
    if not await gate(cq):
        return
    bet = int(cq.data.split(":")[2])
    ok = await try_deduct_balance(cq.from_user.id, bet)
    if not ok:
        await show_alert(cq, f"❌ Не хватает {CURRENCY}!")
        return
    if await get_game(cq.from_user.id):
        await add_balance(cq.from_user.id, bet)
        await show_alert(cq, "У тебя уже есть незавершённая игра.")
        return

    await stat_bet(cq.from_user.id, bet)
    state = joker_new_state(bet)
    await save_game(cq.from_user.id, "joker", bet, state)
    await show(cq, joker_text(state), joker_kb(cq.from_user.id, state))
    await cq.answer()


@dp.callback_query(F.data.startswith("jok:"))
async def cb_joker_pick(cq: CallbackQuery):
    if not await gate(cq):
        return
    parts = cq.data.split(":")
    owner_id = int(parts[1])
    action = parts[2]

    if cq.from_user.id != owner_id:
        await cq.answer("🚫 Это не твоя игра!", show_alert=True)
        return

    if action == "nothing":
        await cq.answer("Это уже пройденные строки.")
        return

    game = await get_game(owner_id)
    if not game or game["game"] != "joker":
        await cq.answer("Нет активной игры.")
        return
    state = game["state"]

    if action == "cashout":
        rounds_passed = len(state["rounds"])
        if rounds_passed == 0:
            await cq.answer("Сначала угадай хотя бы одну карту.")
            return
        mult = joker_multiplier(rounds_passed)
        total = int(game["bet"] * mult)
        profit = total - game["bet"]
        await add_balance(owner_id, total)
        await stat_win(owner_id, profit)
        await delete_game(owner_id)
        state["current"] = None
        result = (f"💰 <b>ЗАБРАЛ {fmt(total)} {CURRENCY}</b> (x{mult})\n"
                  f"└ Чистыми: <b>+{fmt(profit)} {CURRENCY}</b> {e('greedy', '🤑')}")
        await show(cq, joker_text(state, True, result), joker_kb(owner_id, state, True))
        await cq.answer("Забрано!")
        return

    idx = int(action)
    if state.get("current_opened") == idx:
        await cq.answer("Уже открыто")
        return

    skull = state["current"]["skull"]

    if idx == skull:
        state["rounds"].append({"skull": skull, "opened_safe": None})
        state["current"] = None
        state["current_opened"] = None
        await delete_game(owner_id)
        result = (f"{e('skull', '💀')} <b>ЧЕРЕП!</b> Строка {len(state['rounds'])} оказалась роковой.\n"
                  f"└ Сгорело <b>{fmt(game['bet'])} {CURRENCY}</b>")
        await show(cq, joker_text(state, True, result), joker_kb(owner_id, state, True))
        await cq.answer("Череп 💀")
        return

    state["rounds"].append({"skull": skull, "opened_safe": idx})
    state["current"] = joker_new_round()
    state["current_opened"] = None

    await save_game(owner_id, "joker", game["bet"], state)
    await show(cq, joker_text(state), joker_kb(owner_id, state))
    await cq.answer(f"x{joker_multiplier(len(state['rounds']))}")


# ==================== ХОД ИГРЫ: КОСТИ ====================

@dp.callback_query(F.data.startswith("dice:new:"))
async def cb_dice_new(cq: CallbackQuery):
    if not await gate(cq):
        return
    bet = int(cq.data.split(":")[2])
    ok = await try_deduct_balance(cq.from_user.id, bet)
    if not ok:
        await show_alert(cq, f"❌ Недостаточно {CURRENCY}!")
        return

    await stat_bet(cq.from_user.id, bet)
    user_roll = random.randint(1, 6) + random.randint(1, 6)
    bot_roll = random.randint(1, 6) + random.randint(1, 6)

    if user_roll > bot_roll:
        win_mult = 1.95
        win_amt = int(bet * win_mult)
        profit = win_amt - bet
        await add_balance(cq.from_user.id, win_amt)
        await stat_win(cq.from_user.id, profit)
        res = (
            f"{e('trophy', '🎉')} <b>ПОБЕДА!</b>\n"
            f"👤 Твои кубики: <b>{user_roll}</b>\n"
            f"🤖 Бот screamsoon: <b>{bot_roll}</b>\n\n"
            f"💰 Выигрыш: <b>+{fmt(win_amt)} {CURRENCY}</b> (x{win_mult})"
        )
    elif user_roll < bot_roll:
        res = (
            f"{e('skull', '💀')} <b>ПОРАЖЕНИЕ</b>\n"
            f"👤 Твои кубики: <b>{user_roll}</b>\n"
            f"🤖 Бот screamsoon: <b>{bot_roll}</b>\n\n"
            f"💸 Сгорело: <b>{fmt(bet)} {CURRENCY}</b>"
        )
    else:
        await add_balance(cq.from_user.id, bet)
        res = (
            f"🤝 <b>НИЧЬЯ!</b>\n"
            f"👤 Твои кубики: <b>{user_roll}</b>\n"
            f"🤖 Бот screamsoon: <b>{bot_roll}</b>\n\n"
            f"💵 Ставка <b>{fmt(bet)} {CURRENCY}</b> возвращена!"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎲 Ещё на {bet} {CURRENCY}", callback_data=f"dice:new:{bet}")],
        [home_button()],
    ])
    await show(cq, f"{e('dice', '🎲')} <b>КОСТИ (SCREAMSOON)</b>\n\n{res}", kb)
    await cq.answer()


# ==================== ХОД ИГРЫ: КЕЙСЫ ====================

@dp.callback_query(F.data.startswith("case:"))
async def cb_case(cq: CallbackQuery):
    if not await gate(cq):
        return
    key = cq.data.split(":")[1]
    c = CASES.get(key)
    if not c:
        await cq.answer("Нет такого кейса.")
        return

    ok = await try_deduct_balance(cq.from_user.id, c["price"])
    if not ok:
        await show_alert(cq, f"❌ Не хватает {CURRENCY}. Нужно {fmt(c['price'])}.")
        return

    await stat_bet(cq.from_user.id, c["price"])
    prize = open_case(key)
    if prize:
        await add_balance(cq.from_user.id, prize)
        await stat_win(cq.from_user.id, prize - c["price"])
        result = f"{e('trophy', '🎉')} Выпало <b>{fmt(prize)} {CURRENCY}</b>!\n└ Жирно насыпало! {e('greedy', '🤑')}"
    else:
        result = f"{e('skull', '💀')} <b>ПУСТО</b>\n└ Казино screamsoon забрало кейс себе."

    u = await get_user(cq.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Открыть ещё", callback_data=f"case:{key}")],
        [home_button()],
    ])
    await show(cq,
        f"{c['name']} кейс — {fmt(c['price'])} {CURRENCY}\n\n{result}\n\n"
        f"{e('bag', '💼')} Твой баланс: <b>{fmt(u['balance'])} {CURRENCY}</b>", kb)
    await cq.answer()


# ==================== ПЕРЕВОД РЕПЛАЕМ В ЧАТЕ ====================

PAY_RE = re.compile(r"^\s*(?:п|pay|перевод|перевести)\s+(\d+)\s*$", re.IGNORECASE)


async def handle_reply_pay(m: Message) -> bool:
    if not m.text or not m.reply_to_message:
        return False
    match = PAY_RE.match(m.text)
    if not match:
        return False
    if not await gate(m):
        return True

    amount = int(match.group(1))
    if amount <= 0:
        await m.reply("Сумма должна быть больше 0.")
        return True

    target = m.reply_to_message.from_user
    if target.id == m.from_user.id:
        await m.reply("Самому себе переводить нельзя 🤡")
        return True
    if target.is_bot:
        await m.reply("Боту? Ты серьёзно? 🤖")
        return True

    ok = await try_deduct_balance(m.from_user.id, amount)
    if not ok:
        sender = await get_user(m.from_user.id)
        await m.reply(f"💸 У тебя только <b>{fmt(sender['balance'])}</b> {CURRENCY}, "
                      f"а ты пытаешься кинуть {fmt(amount)}.")
        return True

    await get_user(target.id, target.username, target.first_name)
    await add_balance(target.id, amount)

    await m.reply(
        f"{e('money', '💸')} <b>{fmt(amount)} {CURRENCY}</b> успешно улетели от "
        f"@{m.from_user.username or m.from_user.first_name} "
        f"к @{target.username or target.first_name} {e('check', '✅')}")
    return True


# ==================== БАЛАНС В ЧАТЕ ====================

BAL_RE = re.compile(r"^\s*(?:б|бал|баланс|bal|balance)\s*$", re.IGNORECASE)


async def handle_chat_balance(m: Message) -> bool:
    if not m.text or not BAL_RE.match(m.text):
        return False
    if not await gate(m):
        return True

    u = await get_user(m.from_user.id, m.from_user.username, m.from_user.first_name)
    await m.reply(
        f"{e('bag', '💼')} <b>@{m.from_user.username or m.from_user.first_name}</b>, "
        f"твой баланс: <b>{fmt(u['balance'])} {CURRENCY}</b>"
    )
    return True


# ==================== ТРИГГЕРЫ И КОМАНДЫ ЧАТА ====================

TRIGGER_RE = re.compile(
    r"^\s*(джокер|джок|joker|мины|мина|mines|кейс|кейсы|case|кеис|кости|dice)\b(.*)$",
    re.IGNORECASE,
)


async def handle_chat_trigger(m: Message) -> bool:
    if not m.text:
        return False
    match = TRIGGER_RE.match(m.text)
    if not match:
        return False

    game_word = match.group(1).lower()
    rest = match.group(2).strip().split()

    if not await gate(m):
        return True

    if game_word in ("джокер", "джок", "joker"):
        await chat_joker(m, rest)
    elif game_word in ("мины", "мина", "mines"):
        await chat_mines(m, rest)
    elif game_word in ("кейс", "кейсы", "case", "кеис"):
        await chat_case(m, rest)
    elif game_word in ("кости", "dice"):
        await chat_dice(m, rest)
    return True


async def chat_joker(m: Message, args: list[str]):
    if not args or not args[0].isdigit():
        await m.reply("🃏 Формат: <code>джокер 500</code>")
        return
    bet = int(args[0])
    if bet < 100:
        await m.reply(f"🃏 Минимум 100 {CURRENCY}")
        return

    ok = await try_deduct_balance(m.from_user.id, bet)
    if not ok:
        u = await get_user(m.from_user.id)
        await m.reply(f"💸 У тебя {fmt(u['balance'])} {CURRENCY}, ставишь {fmt(bet)}")
        return
    if await get_game(m.from_user.id):
        await add_balance(m.from_user.id, bet)
        await m.reply("🎮 Ты уже играешь!")
        return

    await stat_bet(m.from_user.id, bet)
    state = joker_new_state(bet)
    await save_game(m.from_user.id, "joker", bet, state)
    await m.reply(
        f"🃏 <b>@{m.from_user.username or m.from_user.first_name}</b> "
        f"ставит <b>{fmt(bet)} {CURRENCY}</b>\n\n" + joker_text(state),
        reply_markup=joker_kb(m.from_user.id, state))


async def chat_mines(m: Message, args: list[str]):
    if not args or not args[0].isdigit():
        await m.reply("💣 Формат: <code>мины 100</code>\n└ 5 мин на поле")
        return
    bet = int(args[0])
    if bet < 100:
        await m.reply(f"💣 Минимум 100 {CURRENCY}")
        return

    ok = await try_deduct_balance(m.from_user.id, bet)
    if not ok:
        u = await get_user(m.from_user.id)
        await m.reply(f"💸 У тебя только {fmt(u['balance'])} {CURRENCY}")
        return
    if await get_game(m.from_user.id):
        await add_balance(m.from_user.id, bet)
        await m.reply("🎮 Ты уже играешь!")
        return

    await stat_bet(m.from_user.id, bet)
    state = mines_new_state(MINES_COUNT, bet)
    await save_game(m.from_user.id, "mines", bet, state)
    await m.reply(
        f"💣 <b>@{m.from_user.username or m.from_user.first_name}</b> "
        f"ставит <b>{fmt(bet)} {CURRENCY}</b>\n\n" + mines_text(state),
        reply_markup=mines_kb(m.from_user.id, state))


async def chat_case(m: Message, args: list[str]):
    if not args:
        await m.reply("🎁 Формат: <code>кейс золото</code>")
        return
    case_key = CASE_ALIASES.get(args[0].lower())
    if not case_key:
        await m.reply("🎁 Доступные кейсы: бронза / серебро / золото")
        return
    c = CASES[case_key]
    ok = await try_deduct_balance(m.from_user.id, c["price"])
    if not ok:
        await m.reply(f"💸 {c['name']} стоит {fmt(c['price'])} {CURRENCY}")
        return
    await stat_bet(m.from_user.id, c["price"])
    prize = open_case(case_key)
    if prize:
        await add_balance(m.from_user.id, prize)
        await stat_win(m.from_user.id, prize - c["price"])
        result = f"{e('trophy', '🎉')} Выпало <b>{fmt(prize)} {CURRENCY}</b>!\n└ Жирно насыпало! {e('greedy', '🤑')}"
    else:
        result = f"{e('skull', '💀')} <b>ПУСТО</b>"
    new_bal = (await get_user(m.from_user.id))["balance"]
    await m.reply(
        f"🎁 <b>@{m.from_user.username or m.from_user.first_name}</b> "
        f"открывает {c['name']} за {fmt(c['price'])} {CURRENCY}\n\n{result}\n\n"
        f"{e('bag', '💼')} Баланс: <b>{fmt(new_bal)} {CURRENCY}</b>")


async def chat_dice(m: Message, args: list[str]):
    if not args or not args[0].isdigit():
        await m.reply("🎲 Формат: <code>кости 500</code>")
        return
    bet = int(args[0])
    if bet < 50:
        await m.reply(f"🎲 Минимум 50 {CURRENCY}")
        return

    ok = await try_deduct_balance(m.from_user.id, bet)
    if not ok:
        await m.reply(f"💸 Не хватает {CURRENCY} для ставки!")
        return

    await stat_bet(m.from_user.id, bet)
    user_roll = random.randint(1, 6) + random.randint(1, 6)
    bot_roll = random.randint(1, 6) + random.randint(1, 6)

    if user_roll > bot_roll:
        win_mult = 1.95
        win_amt = int(bet * win_mult)
        profit = win_amt - bet
        await add_balance(m.from_user.id, win_amt)
        await stat_win(m.from_user.id, profit)
        res = (
            f"{e('trophy', '🎉')} <b>ПОБЕДА!</b>\n"
            f"👤 Твои кубики: <b>{user_roll}</b>\n"
            f"🤖 Бот screamsoon: <b>{bot_roll}</b>\n\n"
            f"💰 Выигрыш: <b>+{fmt(win_amt)} {CURRENCY}</b> (x{win_mult})"
        )
    elif user_roll < bot_roll:
        res = (
            f"{e('skull', '💀')} <b>ПОРАЖЕНИЕ</b>\n"
            f"👤 Твои кубики: <b>{user_roll}</b>\n"
            f"🤖 Бот screamsoon: <b>{bot_roll}</b>\n\n"
            f"💸 Сгорело: <b>{fmt(bet)} {CURRENCY}</b>"
        )
    else:
        await add_balance(m.from_user.id, bet)
        res = (
            f"🤝 <b>НИЧЬЯ!</b>\n"
            f"👤 Твои кубики: <b>{user_roll}</b>\n"
            f"🤖 Бот screamsoon: <b>{bot_roll}</b>\n\n"
            f"💵 Ставка <b>{fmt(bet)} {CURRENCY}</b> возвращена!"
        )

    await m.reply(f"{e('dice', '🎲')} <b>КОСТИ (SCREAMSOON)</b>\n\n{res}")


# ==================== КОМАНДА /PAY ====================

@dp.message(Command("pay"))
async def cmd_pay(m: Message):
    if not await gate(m):
        return
    parts = (m.text or "").split()
    if len(parts) != 3 or not parts[2].isdigit():
        await m.answer(f"Формат: <code>/pay @ник сумма</code>")
        return
    target_username = parts[1].lstrip("@")
    amount = int(parts[2])
    if amount <= 0:
        await m.answer("Сумма должна быть > 0.")
        return

    ok = await try_deduct_balance(m.from_user.id, amount)
    if not ok:
        await m.answer(f"❌ Недостаточно {CURRENCY}.")
        return

    target = await find_user_by_username(target_username)
    if not target:
        await add_balance(m.from_user.id, amount)
        await m.answer("❌ Получатель не найден (ему нужно хотя бы раз открыть бота).")
        return
    if target["user_id"] == m.from_user.id:
        await add_balance(m.from_user.id, amount)
        await m.answer("Себе переводить нельзя!")
        return

    await add_balance(target["user_id"], amount)
    await m.answer(f"{e('check', '✅')} Переведено <b>{fmt(amount)} {CURRENCY}</b> пользователю @{target_username}")


# ==================== АДМИН-КОМАНДЫ ====================

def is_admin(m: Message) -> bool:
    return m.from_user.id == ADMIN_ID


async def resolve_target_id(arg: str) -> Optional[int]:
    if arg.startswith("@") or not arg.lstrip("-").isdigit():
        username = arg.lstrip("@")
        target = await find_user_by_username(username)
        return target["user_id"] if target else None
    return int(arg)


@dp.message(Command("give"))
async def cmd_give(m: Message):
    if not is_admin(m):
        return
    parts = (m.text or "").split()

    if m.reply_to_message and len(parts) == 2:
        target = m.reply_to_message.from_user
        try:
            amount = int(parts[1])
        except ValueError:
            await m.answer("Формат: реплай + <code>/give 5000</code>")
            return
        await get_user(target.id, target.username, target.first_name)
        await add_balance(target.id, amount)
        await m.answer(f"✅ @{target.username or target.first_name}: <b>{amount:+}</b> {CURRENCY}")
        try:
            await bot.send_message(target.id, f"💰 Администратор начислил тебе <b>{fmt(amount)} {CURRENCY}</b>")
        except Exception:
            pass
        return

    if len(parts) != 3:
        await m.answer(
            f"Формат:\n"
            f"└ <code>/give user_id 5000</code>\n"
            f"└ <code>/give @username 5000</code>\n"
            f"└ реплай + <code>/give 5000</code>")
        return
    target_id = await resolve_target_id(parts[1])
    if not target_id:
        await m.answer("❌ Юзер не найден")
        return
    try:
        amount = int(parts[2])
    except ValueError:
        await m.answer("Сумма должна быть числом")
        return
    await get_user(target_id)
    await add_balance(target_id, amount)
    await m.answer(f"✅ {target_id}: <b>{amount:+}</b> {CURRENCY}")
    try:
        await bot.send_message(target_id, f"💰 Администратор начислил тебе <b>{fmt(amount)} {CURRENCY}</b>")
    except Exception:
        pass


@dp.message(Command("takebal"))
async def cmd_takebal(m: Message):
    if not is_admin(m):
        return
    parts = (m.text or "").split()
    if len(parts) != 3:
        await m.answer("Формат: <code>/takebal user_id сумма</code>")
        return
    target_id = await resolve_target_id(parts[1])
    if not target_id:
        await m.answer("❌ Юзер не найден")
        return
    try:
        amount = int(parts[2])
    except ValueError:
        await m.answer("Сумма — число")
        return
    await get_user(target_id)
    await add_balance(target_id, -amount)
    await m.answer(f"✅ {target_id}: <b>-{amount}</b> {CURRENCY}")


@dp.message(Command("setbal"))
async def cmd_setbal(m: Message):
    if not is_admin(m):
        return
    parts = (m.text or "").split()
    if len(parts) != 3:
        await m.answer("Формат: <code>/setbal user_id сумма</code>")
        return
    target_id = await resolve_target_id(parts[1])
    if not target_id:
        await m.answer("❌ Юзер не найден")
        return
    try:
        amount = int(parts[2])
    except ValueError:
        await m.answer("Сумма — число")
        return
    await get_user(target_id)
    await set_balance(target_id, amount)
    await m.answer(f"✅ {target_id} = <b>{fmt(amount)}</b> {CURRENCY}")


@dp.message(Command("giveall"))
async def cmd_giveall(m: Message):
    if not is_admin(m):
        return
    parts = (m.text or "").split()
    if len(parts) != 2:
        await m.answer("Формат: <code>/giveall сумма</code>")
        return
    try:
        amount = int(parts[1])
    except ValueError:
        await m.answer("Сумма — число")
        return
    n = await give_all(amount)
    await m.answer(f"✅ Всем <b>{n}</b> юзерам начислено: <b>{amount:+}</b> {CURRENCY}")


# ==================== ПРОВЕРКА ПОДПИСКИ ПО КНОПКЕ ====================

@dp.callback_query(F.data == "check_sub")
async def cb_check_sub(cq: CallbackQuery):
    if not await is_subscribed(cq.from_user.id):
        await cq.answer("Ты ещё не подписан!", show_alert=True)
        return
    u = await get_user(cq.from_user.id, cq.from_user.username, cq.from_user.first_name)
    if not u["sub_rewarded"]:
        await add_balance(cq.from_user.id, SUBSCRIBE_REWARD)
        await mark_sub_rewarded(cq.from_user.id)
        await cq.answer(f"+{SUBSCRIBE_REWARD} {CURRENCY} за подписку!", show_alert=True)
    if cq.message.chat.type == ChatType.PRIVATE:
        await render_menu(cq, edit=True)
    else:
        await cq.answer("Подписка подтверждена!")


# ==================== ЧАТ-СЛУШАТЕЛЬ ====================

@dp.message(F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def chat_listener(m: Message):
    if await handle_reply_pay(m):
        return
    if await handle_chat_balance(m):
        return
    await handle_chat_trigger(m)


# ==================== ЗАПУСК ====================

@dp.shutdown()
async def on_shutdown():
    if _pg_pool:
        await _pg_pool.close()
        print("[БД] Пул соединений закрыт.")


async def main():
    await init_db()
    print(f"Казино screamsoon успешно запущено 🎰 [{DB_BACKEND}]")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
