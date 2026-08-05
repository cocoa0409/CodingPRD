"""The logical clock.

PRD 2.5: nothing in this system reads the host machine's wall clock.  The clock
reads exactly 2026-05-01T00:00:00Z from server start until a ProgramAdmin moves
it, and never falls back to real time afterwards.
"""

from constants import DEFAULT_CLOCK_UTC
from timefmt import parse_instant, instant_date

_state = {"now": parse_instant(DEFAULT_CLOCK_UTC)}


def now():
    """The current logical clock instant (aware UTC, millisecond resolution)."""
    return _state["now"]


def today():
    """The logical clock date."""
    return instant_date(_state["now"])


def set_now(instant):
    _state["now"] = instant
    return _state["now"]


def reset():
    _state["now"] = parse_instant(DEFAULT_CLOCK_UTC)
