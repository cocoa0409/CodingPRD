"""Single server-controlled logical clock.

On server startup the clock reads exactly 2026-01-01T00:00:00Z and holds that
value until an administrator advances it via POST /_clock/set_current_utc.
Every deadline, expiry, in-force window, and age computation reads this clock,
never wall-clock time.
"""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": _DEFAULT}


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt
