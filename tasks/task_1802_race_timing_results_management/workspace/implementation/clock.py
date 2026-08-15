"""Server-maintained logical clock.

Boots to exactly 2026-08-01T00:00:00Z. Never falls back to wall-clock time.
Set via POST /race-timing/_clock/set_current_utc. Window and cutoff
comparisons use second-precision logical time (now_sec()); stamps use the
full stored value.
"""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_current = _DEFAULT


def now():
    return _current


def set_now(dt):
    global _current
    _current = dt


def now_sec():
    return _current.replace(microsecond=0)
