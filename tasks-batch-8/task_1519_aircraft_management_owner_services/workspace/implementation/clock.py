"""Logical clock. Reads exactly 2026-08-01T00:00:00Z before being set;
never falls back to wall-clock time."""
from datetime import datetime, timezone


_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_current = _DEFAULT


def now():
    return _current


def set_current(dt):
    global _current
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _current = dt.astimezone(timezone.utc)
    return _current
