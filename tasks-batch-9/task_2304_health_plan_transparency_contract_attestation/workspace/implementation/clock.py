"""The single server-side logical clock (PRD 2.5).

There is no wall clock anywhere in this service.  Every timestamp, day count,
month boundary and deadline comparison reads this module.  At startup the clock
reads 2026-08-01T00:00:00Z; a PlatformOperator moves it forward (never back).
"""

import calendar
import re
from datetime import date, datetime, timedelta, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": DEFAULT_CLOCK}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATETIME_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"([Zz]|[+-]00:?00)$"
)


def now():
    return _state["now"]


def set_now(dt):
    _state["now"] = dt


def today():
    return _state["now"].date()


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso(_state["now"])


def today_iso():
    return _state["now"].date().isoformat()


def parse_datetime(value):
    """Parse an ISO 8601 UTC instant.  Returns None when malformed."""
    if not isinstance(value, str):
        return None
    m = DATETIME_RE.match(value)
    if not m:
        return None
    frac = m.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    try:
        return datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def parse_date(value):
    """Parse an ISO YYYY-MM-DD date.  Returns None when malformed."""
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def is_month(value):
    return isinstance(value, str) and bool(MONTH_RE.match(value))


def month_of(value):
    """YYYY-MM of a date, datetime or ISO date string."""
    if isinstance(value, str):
        return value[:7]
    return "%04d-%02d" % (value.year, value.month)


def month_bounds(month):
    """(first instant, first instant of next month) for a YYYY-MM string."""
    year = int(month[0:4])
    mon = int(month[5:7])
    start = datetime(year, mon, 1, tzinfo=timezone.utc)
    if mon == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, mon + 1, 1, tzinfo=timezone.utc)
    return start, end


def days_in_month(month):
    return calendar.monthrange(int(month[0:4]), int(month[5:7]))[1]


def next_month_first_day(month):
    """ISO date of the first day of the month following a YYYY-MM string."""
    year = int(month[0:4])
    mon = int(month[5:7])
    if mon == 12:
        return date(year + 1, 1, 1).isoformat()
    return date(year, mon + 1, 1).isoformat()


def plus_days(d, n):
    return d + timedelta(days=n)


def end_of_day_ms(d):
    """The 23:59:59.999Z instant of a date."""
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=timezone.utc)


def reset():
    _state["now"] = DEFAULT_CLOCK
