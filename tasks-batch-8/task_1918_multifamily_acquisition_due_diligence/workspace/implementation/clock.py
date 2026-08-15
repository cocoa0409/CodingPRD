"""Logical clock. Startup default 2026-08-01T00:00:00Z; never falls back to wall clock."""

from datetime import datetime, timezone

_INITIAL = "2026-08-01T00:00:00Z"
_current_utc = _INITIAL


def get_current_utc():
    return _current_utc


def set_current_utc(to_iso8601):
    global _current_utc
    # normalize to ...Z format
    dt = parse_iso(to_iso8601)
    _current_utc = format_iso(dt)
    return _current_utc


def parse_iso(value):
    """Parse ISO 8601 string; return aware datetime in UTC."""
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # seconds precision (clock uses Z without fractional)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_clock_dt():
    return parse_iso(_current_utc)


def date_part(dt):
    """Date portion of an aware datetime (for calendar-day diffs)."""
    return dt.date()


def calendar_days_between(start_dt, end_dt):
    """Calendar days between the date portions: (end.date - start.date).days."""
    return (date_part(end_dt) - date_part(start_dt)).days
