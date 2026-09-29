"""Logical clock (PRD 2.4). Default 2026-08-01T00:00:00Z, resets on every boot."""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": _DEFAULT}


def now():
    return _state["now"]


def set_now(value):
    _state["now"] = value


def reset():
    _state["now"] = _DEFAULT
