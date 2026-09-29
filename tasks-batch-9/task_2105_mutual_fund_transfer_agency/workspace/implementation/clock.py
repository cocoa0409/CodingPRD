"""The logical clock.  It starts at 2026-08-01T00:00:00Z and only moves when set."""
from datetime import datetime, timezone

import dates

DEFAULT_CLOCK_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_current = DEFAULT_CLOCK_UTC


def now():
    return _current


def set_now(dt):
    global _current
    _current = dt.astimezone(timezone.utc)
    return _current


def reset():
    global _current
    _current = DEFAULT_CLOCK_UTC


def now_iso():
    return dates.fmt_instant(_current)


def today():
    return _current.date()


def time_of_day():
    return _current.timetz().replace(tzinfo=None)


def real_now_iso():
    return dates.fmt_instant(datetime.now(timezone.utc))
