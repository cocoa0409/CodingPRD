"""Logical server clock (PRD 2.5). Wall-clock time is never consulted.

Startup default is exactly 2026-08-01T00:00:00Z; the clock only moves when
POST /_clock/set_current_utc advances it.
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
