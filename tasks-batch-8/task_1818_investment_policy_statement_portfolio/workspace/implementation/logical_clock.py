"""Logical clock. Server startup default is exactly 2026-08-01T00:00:00Z.
Every timestamp-dependent rule reads this clock, never the wall clock."""
from datetime import datetime, timezone

_current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _current


def set_current(dt):
    global _current
    _current = dt.astimezone(timezone.utc)


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits, Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_or_none(dt):
    return None if dt is None else fmt(dt)
