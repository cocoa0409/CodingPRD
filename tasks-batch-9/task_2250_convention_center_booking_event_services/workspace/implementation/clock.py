"""The server logical clock (PRD 2.5).

Every deadline, booking window, order-timing decision and date comparison in
this service reads this clock, never the host wall clock.  Before it is ever
set it reads exactly 2026-08-01T00:00:00Z and it never falls back to real time.
The value lives in a module global, so a fresh process always starts at the
declared epoch.
"""

from datetime import datetime, timezone

EPOCH = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

_current = EPOCH


def now():
    """The current logical instant, timezone-aware UTC."""
    return _current


def today():
    """The calendar date of the logical clock in UTC."""
    return _current.date()


def set_now(dt):
    global _current
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _current = dt.astimezone(timezone.utc)
    return _current


def reset():
    global _current
    _current = EPOCH
