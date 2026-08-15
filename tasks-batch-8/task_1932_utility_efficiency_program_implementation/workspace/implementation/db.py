"""In-memory data store for the utility efficiency program API.

All state lives in plain Python dicts. The store is re-created empty on every
process boot (the harness restarts the server before every test), and no
entity data is seeded here by design.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from threading import RLock


LOCK = RLock()

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
_current_clock: datetime = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_clock() -> datetime:
    return _current_clock


def set_clock(value: datetime) -> None:
    global _current_clock
    _current_clock = value


def reset_clock() -> None:
    global _current_clock
    _current_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    """Return the current logical-clock instant as an ISO-8601 UTC string with
    three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    dt = get_clock()
    return format_dt(dt)


def format_dt(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # 3 fractional digits
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_dt(value) -> datetime:
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    else:
        raise ValueError(f"unsupported datetime value: {value!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


def request_id() -> str:
    return "req_" + uuid.uuid4().hex[:20]


# ---------------------------------------------------------------------------
# Entity stores
# ---------------------------------------------------------------------------

programs: dict[str, dict] = {}
contractors: dict[str, dict] = {}
certifications: dict[str, dict] = {}
customers: dict[str, dict] = {}
leads: dict[str, dict] = {}
projects: dict[str, dict] = {}
work_orders: dict[str, dict] = {}
inspectors: dict[str, dict] = {}
inspections: dict[str, dict] = {}
payments: dict[str, dict] = {}
complaints: dict[str, dict] = {}
reports: dict[str, dict] = {}


def stamp_new(record: dict) -> dict:
    """Populate system common fields for a freshly created record."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record: dict) -> None:
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
