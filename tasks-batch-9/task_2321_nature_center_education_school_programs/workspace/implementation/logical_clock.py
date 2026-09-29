"""The logical program clock (PRD 2.5).

Nothing in this system reads real wall-clock time for business logic.  Before
any call to POST /_clock/set_current_utc the clock reads exactly
2026-08-01T00:00:00Z.
"""

from datetime import datetime, timedelta, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_NOW}


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)


def reset():
    _state["now"] = DEFAULT_NOW


def week_bounds(instant=None):
    """Half-open ISO program week [Monday 00:00:00Z, +7 days)."""
    ref = (instant or now()).astimezone(timezone.utc)
    midnight = datetime(ref.year, ref.month, ref.day, tzinfo=timezone.utc)
    start = midnight - timedelta(days=ref.weekday())
    return start, start + timedelta(days=7)


def in_current_week(dt):
    if dt is None:
        return False
    start, end = week_bounds()
    return start <= dt < end
