"""Logical clock and date arithmetic (PRD section 2.5).

The service never reads the host wall clock. A single logical clock, seeded at
2026-08-01T00:00:00Z on boot, is the sole source of "now".
"""
import calendar
import re
from datetime import date, datetime, timedelta, timezone

DEFAULT_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_ISO_DT = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


class Clock(object):
    def __init__(self):
        self.now = DEFAULT_NOW

    def set(self, dt):
        dt = dt.astimezone(timezone.utc)
        self.now = dt.replace(microsecond=(dt.microsecond // 1000) * 1000)

    def instant(self):
        return self.now

    def iso(self):
        return format_dt(self.now)

    def today(self):
        return self.now.date()


CLOCK = Clock()


def reset_clock():
    CLOCK.now = DEFAULT_NOW


def format_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_datetime(value):
    if not isinstance(value, str):
        raise ValueError("not a string")
    m = _ISO_DT.match(value.strip())
    if not m:
        raise ValueError("not an ISO 8601 datetime")
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    tz = timezone.utc
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        tz = timezone(sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4])))
    dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=tz)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str):
        raise ValueError("not a string")
    m = _ISO_DATE.match(value.strip())
    if not m:
        raise ValueError("not an ISO 8601 date")
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def format_date(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def add_months(d, months):
    """Calendar-month addition keeping the day-of-month, clamped to month end."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def add_days_dt(dt, days):
    return dt + timedelta(days=days)


def inclusive_days(start, end):
    """Day count inclusive of both endpoints."""
    return (end - start).days + 1
