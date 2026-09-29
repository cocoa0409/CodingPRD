"""The logical plant clock (PRD 2.4).

Every server-stamped instant, every date default and every window rule reads
this clock.  Before any client moves it the clock reads exactly
2026-08-01T00:00:00Z and the server never falls back to host wall-clock time.
"""

from datetime import datetime

from util import iso_ts

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0)

_state = {"now": DEFAULT_NOW}


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt


def reset():
    _state["now"] = DEFAULT_NOW


def now_iso():
    return iso_ts(_state["now"])


def today():
    return _state["now"].date()


def today_str():
    return _state["now"].date().isoformat()
