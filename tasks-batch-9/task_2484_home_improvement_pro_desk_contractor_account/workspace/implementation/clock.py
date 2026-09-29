"""Logical clock (PRD 2.4).

Before any client sets the clock it reads exactly 2026-08-01T00:00:00Z; the server
never falls back to wall-clock time.
"""
from datetime import datetime, timezone, timedelta, date

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_NOW}


def reset():
    _state["now"] = DEFAULT_NOW


def get_now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def now_iso():
    return fmt(get_now())


def today():
    return get_now().date()


def parse_datetime(value):
    """Parse an ISO-8601 instant. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO calendar date (YYYY-MM-DD). Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def fmt_date(d):
    return None if d is None else d.isoformat()


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def whole_days_between(later, earlier):
    """floor((later - earlier) / 86400) in whole days."""
    return int((later - earlier).total_seconds() // 86400)
