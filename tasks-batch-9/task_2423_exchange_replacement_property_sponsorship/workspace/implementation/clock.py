"""The single logical clock (PRD 2.4).

The startup default is exactly 2026-08-01T00:00:00Z and nothing in this
service ever reads the host wall clock.
"""
from constants import CLOCK_DEFAULT

_state = {"now": CLOCK_DEFAULT}


def now():
    return _state["now"]


def set_now(instant):
    _state["now"] = instant
    return _state["now"]
