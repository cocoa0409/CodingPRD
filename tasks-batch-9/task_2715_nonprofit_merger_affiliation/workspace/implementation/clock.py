"""The logical clock — PRD section 2.4.

The server's startup default clock value is exactly 2026-08-01T00:00:00Z and it
must never fall back to real wall-clock time.
"""

import re
from datetime import datetime, timedelta

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0)

_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class LogicalClock:
    def __init__(self):
        self.value = DEFAULT_CLOCK

    def reset(self):
        self.value = DEFAULT_CLOCK

    def now(self):
        return self.value

    def now_iso(self):
        return fmt_ts(self.value)

    def today(self):
        return self.value.date()

    def set(self, new_value):
        previous = self.value
        self.value = new_value
        return previous


CLOCK = LogicalClock()


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_ts(text):
    """Parse an ISO 8601 UTC timestamp. Returns a naive UTC datetime or None."""
    if not isinstance(text, str):
        return None
    m = _TS_RE.match(text.strip())
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        oh, om = int(body[:2]), int(body[2:4])
        dt = dt - sign * timedelta(hours=oh, minutes=om)
    return dt


def parse_date(text):
    """Parse a YYYY-MM-DD calendar date. Returns a date or None."""
    if not isinstance(text, str) or not _DATE_RE.match(text.strip()):
        return None
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def date_at_midnight(d):
    """Render a calendar date as an instant at 00:00:00.000Z."""
    return datetime(d.year, d.month, d.day, 0, 0, 0, 0)


def add_days(value, days):
    return value + timedelta(days=days)
