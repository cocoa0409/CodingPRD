"""Deterministic logical clock (PRD 2.4).

The service never reads the wall clock for any stored timestamp.  The clock
starts at 2026-08-01T00:00:00Z on every boot and only moves when
POST /_clock/set_current_utc says so — forward or backward.
"""

from datetime import datetime

from timeutil import UTC

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_state = {"now": DEFAULT_NOW}


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(UTC)
    return _state["now"]


def reset():
    _state["now"] = DEFAULT_NOW
