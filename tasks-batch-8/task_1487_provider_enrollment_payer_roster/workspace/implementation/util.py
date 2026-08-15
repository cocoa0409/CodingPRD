"""Date/timestamp utilities. Dates are strict YYYY-MM-DD strings; timestamps are
ISO 8601 UTC with exactly three fractional digits."""
import calendar
import re
from datetime import date, datetime, timezone

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(s):
    """Parse a strict YYYY-MM-DD date string -> datetime.date, or None."""
    if not isinstance(s, str) or not DATE_RE.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_timestamp(s):
    """Parse an ISO 8601 timestamp -> aware datetime in UTC, or None."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """Format an aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def last_day_of_month(d):
    """Last calendar day of the month containing date d (Gregorian)."""
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
