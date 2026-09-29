"""The deterministic logical clock (§2.4) plus date/datetime helpers.

The clock begins at 2026-08-01T00:00:00Z on a freshly started process and is
only ever moved by POST /_clock/set_current_utc. Nothing in this service reads
the host machine's wall clock.
"""

import calendar
import re
from datetime import date, datetime, timedelta, timezone

from constants import CLOCK_EPOCH_ISO

_ISO_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,6})\d*)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": _EPOCH}


def reset():
    _state["now"] = _EPOCH


def now():
    """Current logical-clock instant (timezone-aware UTC)."""
    return _state["now"]


def set_now(dt):
    _state["now"] = dt.astimezone(timezone.utc)
    return _state["now"]


def today():
    """Calendar date of the logical clock."""
    return now().date()


# ------------------------------------------------------------------ parsing


def parse_datetime(value):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _ISO_DT_RE.match(value.strip())
    if not m:
        # bare date is also acceptable as midnight UTC
        d = parse_date(value)
        if d is None:
            return None
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    year, month, day, hour, minute, second, frac, tz = m.groups()
    try:
        micro = int((frac or "0").ljust(6, "0")) if frac else 0
        dt = datetime(
            int(year), int(month), int(day), int(hour), int(minute),
            int(second or 0), micro,
        )
    except ValueError:
        return None
    if tz in (None, "Z", "z"):
        return dt.replace(tzinfo=timezone.utc)
    sign = 1 if tz[0] == "+" else -1
    body = tz[1:].replace(":", "")
    offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return (dt - sign * offset).replace(tzinfo=timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date; returns None when invalid."""
    if not isinstance(value, str):
        return None
    m = _ISO_DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


# ------------------------------------------------------------------ formatting


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_date(d):
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


# ------------------------------------------------------------------ arithmetic


def add_days_dt(dt, days):
    return dt + timedelta(days=days)


def add_days(d, days):
    return d + timedelta(days=days)


def last_day_of_month(d):
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def add_months(d, months):
    total = (d.year * 12 + (d.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def whole_days_between(anchor, later):
    """floor((later - anchor) / 1 day) in whole elapsed days."""
    return int((later - anchor).total_seconds() // 86400)


def month_no(value):
    """Calendar month number 1..12 of an ISO date string or date object."""
    if value is None:
        return None
    if isinstance(value, str):
        d = parse_date(value)
        return None if d is None else d.month
    return value.month
