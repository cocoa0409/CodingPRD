"""Logical UTC clock, ISO-8601 rendering, and the business-day calendar (PRD 2.4, 2.9)."""

import datetime
import re

CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
HOLIDAY_CALENDAR = frozenset(["2026-09-07", "2026-11-26", "2026-11-27", "2026-12-25"])

_DT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?Z$")
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

UTC = datetime.timezone.utc


class _Clock(object):
    """The logical clock. Starts at the declared default and never reads wall time."""

    def __init__(self):
        self.now = parse_dt(CLOCK_STARTUP_DEFAULT)

    def set(self, dt):
        self.now = dt


def parse_dt(value):
    """Parse an ISO-8601 UTC instant with a literal Z offset. Returns None on failure."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value)
    if not m:
        return None
    frac = m.group(7) or "0"
    micro = int((frac + "000000")[:6])
    try:
        return datetime.datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micro, tzinfo=UTC)
    except ValueError:
        return None


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date. Returns None on failure."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value)
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt_ts(dt):
    """created_at / updated_at rendering: exactly three fractional-second digits."""
    if dt is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000)


def fmt_dt(dt):
    """Every other server-computed instant: second precision unless sub-second data exists."""
    if dt is None:
        return None
    if dt.microsecond:
        return fmt_ts(dt)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def is_business_day(d):
    if d.weekday() >= 5:
        return False
    return fmt_date(d) not in HOLIDAY_CALENDAR


def add_business_days(anchor_date, count):
    """Step forward one calendar day at a time; the anchor day itself is never counted."""
    d = anchor_date
    remaining = count
    while remaining > 0:
        d = d + datetime.timedelta(days=1)
        if is_business_day(d):
            remaining -= 1
    return d


def end_of_day(d):
    """A business-day deadline lands at 23:59:59Z on the resulting date."""
    return datetime.datetime(d.year, d.month, d.day, 23, 59, 59, 0, tzinfo=UTC)


def business_deadline(anchor_date, business_days):
    return end_of_day(add_business_days(anchor_date, business_days))


def add_hours(dt, hours):
    """Cure windows: exact hour arithmetic, no calendar skipping."""
    return dt + datetime.timedelta(hours=hours)


def add_days(dt, days):
    """Exact day arithmetic preserving the time of day; no month or leap adjustment."""
    return dt + datetime.timedelta(days=days)


def add_minutes(dt, minutes):
    return dt + datetime.timedelta(minutes=minutes)


CLOCK = _Clock()


def now():
    return CLOCK.now


def now_ts():
    return fmt_ts(CLOCK.now)


def now_dt_str():
    return fmt_dt(CLOCK.now)
