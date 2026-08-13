"""Server-side logical clock. Never reads the wall clock for business rules.

Startup default is exactly 2026-08-01T00:00:00Z per PRD section 2.4.
"""
from datetime import datetime, timezone

_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_current = _START


def now():
    return _current


def set_current(dt):
    global _current
    _current = dt


def to_z(dt):
    """Serialize with three fractional digits and a Z suffix."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO-8601 datetime. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO date (YYYY-MM-DD). Returns a date or None."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.strptime(value, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    return dt.date()
