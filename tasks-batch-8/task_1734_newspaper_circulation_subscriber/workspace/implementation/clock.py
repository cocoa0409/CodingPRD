"""Logical clock. Starts at exactly 2026-08-01T00:00:00Z and never falls back
to wall-clock time. Advanced only via POST /_clock/set_current_utc. 'today'
for every date rule in the system is the UTC date of this clock."""
from datetime import datetime, timezone

_current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now_dt():
    return _current


def set_current(dt):
    global _current
    _current = dt
