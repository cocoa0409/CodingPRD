"""Logical clock. Server startup default is exactly 2026-05-01T00:00:00Z and the
clock never falls back to wall time; it only moves via POST /api/_clock/set_current_utc."""
from datetime import datetime, timezone

_NOW = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _NOW


def set_now(dt):
    global _NOW
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _NOW = dt.astimezone(timezone.utc)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 string (date-only or datetime, 'Z' or offset) into an
    aware UTC datetime. Raises ValueError on malformed input."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    t = value.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def today_midnight():
    n = _NOW
    return n.replace(hour=0, minute=0, second=0, microsecond=0)
