"""The logical server clock (PRD 2.9).

All time-dependent logic reads from a single server clock that a SupportAgent
may set via POST /v1/_clock/set_current_utc. Until set, the clock falls back to
real UTC wall-clock time. State is in-memory only and reset on every boot.
"""
from datetime import datetime, timezone

_current_utc = None  # datetime (tz-aware) or None -> use wall clock


def set_now(dt):
    global _current_utc
    _current_utc = dt


def now():
    if _current_utc is not None:
        return _current_utc
    return datetime.now(timezone.utc)


def reset():
    global _current_utc
    _current_utc = None
