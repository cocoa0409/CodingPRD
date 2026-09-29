"""The service-wide logical UTC clock (PRD section 2.5).

The clock is initialised to the mandatory default 2026-08-01T00:00:00Z on every
fresh service start and is only ever moved by the clock-setting endpoint.
"""
from datetime import datetime, timezone

DEFAULT_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_INSTANT}


def now():
    return _state["now"]


def set_now(instant):
    _state["now"] = instant.astimezone(timezone.utc)
    return _state["now"]


def reset():
    _state["now"] = DEFAULT_INSTANT
