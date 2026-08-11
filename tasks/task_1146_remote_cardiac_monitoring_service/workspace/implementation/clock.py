"""Logical clock. Startup default 2026-05-01T00:00:00Z; never falls back to wall time."""
from datetime import datetime, timezone

_current = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _current


def set_current(dt):
    global _current
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _current = dt.astimezone(timezone.utc)
