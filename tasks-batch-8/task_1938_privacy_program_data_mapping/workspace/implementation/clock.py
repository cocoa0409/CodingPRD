"""Logical clock. Defaults to exactly 2026-08-01T00:00:00Z; never falls back
to wall time. Advanced only via POST /_clock/set_current_utc."""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_current = _DEFAULT


def now():
    return _current


def set_current(dt):
    global _current
    _current = dt
