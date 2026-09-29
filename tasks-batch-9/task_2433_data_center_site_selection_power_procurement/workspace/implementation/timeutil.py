"""ISO 8601 UTC parsing and formatting.

PRD 2.4: timestamps are ISO 8601 UTC strings with exactly three fractional-second
digits. PRD 2.6: the server keeps a logical UTC clock; every window test, expiry
decision and system-stamped instant reads that clock, never the host wall clock.
"""

from datetime import datetime, timedelta, timezone


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Raises ValueError when the value is not a parseable ISO 8601 instant.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def days_between(later, earlier):
    """Whole days from `earlier` to `later` (floored, may be negative)."""
    delta = later - earlier
    return delta // timedelta(days=1)


def plus_days(dt, days):
    return dt + timedelta(days=int(days))
