"""Logical clock: global, starts at 2026-05-01T00:00:00Z, advanced via /_clock/set_current_utc."""
from db import db
from util import DEFAULT_LOGICAL_CLOCK


# Global logical clock (single for all distributors)
_STATE = {"now": DEFAULT_LOGICAL_CLOCK}


def get_logical_clock():
    return _STATE["now"]


def set_logical_clock(dt):
    _STATE["now"] = dt
