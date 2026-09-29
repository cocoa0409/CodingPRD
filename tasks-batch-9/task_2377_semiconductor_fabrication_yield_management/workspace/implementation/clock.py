"""The logical clock (PRD 2.4).

Time in this system is a logical clock, never wall-clock time.  Before it is
ever set it reads exactly 2026-08-01T00:00:00Z and it never falls back to real
time.
"""
from datetime import datetime, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = DEFAULT_NOW


def now():
    return _current


def set_now(dt):
    global _current
    _current = dt.astimezone(timezone.utc)
    return _current
