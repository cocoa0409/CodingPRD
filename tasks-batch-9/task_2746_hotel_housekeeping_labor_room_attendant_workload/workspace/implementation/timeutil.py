"""Timestamp and calendar-date helpers.

PRD 2.4: timestamps are ISO 8601 UTC rendered with exactly three fractional
digits (e.g. 2026-08-01T06:15:00.000Z).  Date-typed fields are plain YYYY-MM-DD
calendar dates with no time component.
"""

import re
from datetime import date, datetime, timedelta, timezone


_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_iso_datetime(text):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if not isinstance(text, str):
        return None
    m = _TS_RE.match(text.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        if offset in (None, "Z", "z"):
            tz = timezone.utc
        else:
            sign = 1 if offset[0] == "+" else -1
            body = offset[1:].replace(":", "")
            tz = timezone(sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4])))
        dt = datetime(year, month, day, hour, minute, second, micro, tzinfo=tz)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


def format_iso_datetime(dt):
    """Render an aware datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def parse_iso_date(text):
    """Parse a YYYY-MM-DD calendar date, or None."""
    if not isinstance(text, str):
        return None
    m = _DATE_RE.match(text.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def format_iso_date(d):
    if d is None:
        return None
    if isinstance(d, str):
        return d
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def minutes_between(start, end):
    """Signed exact minutes between two instants, as a Fraction-friendly rational."""
    from fractions import Fraction

    delta = end - start
    total_seconds = Fraction(delta.days * 86400 + delta.seconds) + Fraction(delta.microseconds, 1000000)
    return total_seconds / 60


def add_days(dt, days):
    return dt + timedelta(days=days)


def date_minus_days(d, days):
    return d - timedelta(days=days)
