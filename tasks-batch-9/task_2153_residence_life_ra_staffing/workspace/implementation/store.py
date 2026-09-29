"""In-memory store, logical clock and version bookkeeping.

The store starts completely empty on every boot; nothing is ever seeded.
"""
import itertools
import threading
import uuid
from datetime import datetime, timedelta, timezone

from constants import DEFAULT_CLOCK_UTC

_LOCK = threading.RLock()
_SEQ = itertools.count(1)

TABLE_NAMES = (
    "buildings", "floors", "rooms", "students", "applications", "ras",
    "shifts", "incidents", "conduct_cases", "inspections", "charges",
    "rc_cases", "events", "breaks",
)

DB = {name: {} for name in TABLE_NAMES}

_clock = {"now": None}


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------
def parse_iso(value):
    """Parse an ISO-8601 instant. Raises ValueError on bad input."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not a datetime")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now():
    return datetime.now(timezone.utc)


def now():
    """The logical clock instant."""
    if _clock["now"] is None:
        _clock["now"] = parse_iso(DEFAULT_CLOCK_UTC)
    return _clock["now"]


def now_iso():
    return fmt_iso(now())


def set_clock(dt):
    previous = now()
    _clock["now"] = dt
    return previous


def days(n):
    return timedelta(days=n)


# --------------------------------------------------------------------------
# entity helpers
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def insert(table, entity_type, fields):
    stamp = fmt_iso(wall_now())
    row = {
        "_type": entity_type,
        "_seq": next(_SEQ),
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    row.update(fields)
    DB[table][row["id"]] = row
    return row


def touch(row):
    row["updated_at"] = fmt_iso(wall_now())
    row["version"] = int(row.get("version", 1)) + 1


def all_rows(table):
    return sorted(DB[table].values(), key=lambda r: (r["created_at"], r["_seq"]))


def get(table, row_id):
    if not isinstance(row_id, str):
        return None
    return DB[table].get(row_id)


def reset():
    for name in TABLE_NAMES:
        DB[name].clear()
    _clock["now"] = None
