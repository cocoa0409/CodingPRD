"""Logical server clock (PRD section 2.5).

Wall-clock time is never consulted.  Before any clock operation the reading is
exactly 2026-08-01T00:00:00Z.  The clock moves only through
POST /_clock/set_current_utc; advancing it mutates no entity.
"""
from datetime import datetime, timezone

_current = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _current


def set_current(dt):
    global _current
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _current = dt.astimezone(timezone.utc)
