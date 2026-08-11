"""Logical clock. Starts at exactly 2026-05-01T00:00:00Z and never falls back
to wall-clock time. Advanced only via POST /_clock/set_current_utc."""
from datetime import datetime, timezone

_current = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def now_dt():
    return _current


def set_current(dt):
    global _current
    _current = dt
