"""Logical clock per PRD 2.4. Starts at exactly 2026-08-01T00:00:00Z; never
reads wall-clock time for temporal decisions."""

from datetime import datetime, timezone


DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = DEFAULT_NOW


def now():
    return _now


def set_now(dt):
    global _now
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _now = dt.astimezone(timezone.utc)
    return _now
