"""Datetime / date parsing and formatting utilities.

All timestamps on the wire are ISO-8601 UTC with exactly three fractional
digits (PRD section 2.2 / 2.5).
"""
import re
from datetime import datetime, timezone

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_iso(value):
    """Parse an ISO-8601 datetime string into an aware UTC datetime.

    Returns None when the value is not a parseable datetime string.
    Naive inputs are interpreted as UTC.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """Format an aware datetime as ISO-8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000,)


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date; returns a date or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
