"""Logical clock (PRD §2.5). Startup default: 2026-08-01T00:00:00Z; never falls back to wall clock."""
from datetime import datetime, timezone

_STARTUP_ISO = "2026-08-01T00:00:00Z"

_state = {"current": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return _state["current"]


def set_current(dt):
    _state["current"] = dt


def now_iso():
    return format_iso(_state["current"])


def format_iso(dt):
    """ISO 8601 UTC with three fractional digits, trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def parse_iso(s):
    """Parse ISO 8601 datetime. Returns timezone-aware datetime or raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse strict YYYY-MM-DD date. Raises ValueError otherwise."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    parts = s.split("-")
    if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        raise ValueError("bad date format")
    from datetime import date
    return date(int(parts[0]), int(parts[1]), int(parts[2]))
