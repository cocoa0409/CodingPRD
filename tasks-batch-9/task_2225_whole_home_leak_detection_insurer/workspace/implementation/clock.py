"""The logical clock (PRD section 2.4).

Time is never read from the host wall clock.  The clock starts at exactly
2026-08-01T00:00:00Z on every boot and only moves when a ProgramAdmin posts to
/_clock/set_current_utc.
"""
from datetime import datetime, timedelta, timezone

from config import CLOCK_DEFAULT_ISO

_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": _DEFAULT}


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)
    return _state["now"]


def reset():
    _state["now"] = _DEFAULT


def plus_minutes(dt, minutes):
    return dt + timedelta(minutes=float(minutes))


def plus_hours(dt, hours):
    return dt + timedelta(hours=float(hours))


def plus_days(dt, days):
    return dt + timedelta(days=float(days))


DEFAULT_ISO = CLOCK_DEFAULT_ISO
