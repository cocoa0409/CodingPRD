"""Timestamp parsing and formatting helpers.

PRD §2.4 / §2.2: ISO 8601 UTC with three fractional digits, e.g.
"2025-05-24T10:30:00.123Z". Inputs may carry a trailing 'Z' or an explicit
offset, and may or may not carry fractional seconds; all are normalized to UTC.
"""
from datetime import datetime, timezone, timedelta


def parse_iso(value):
    """Parse an ISO 8601 timestamp into a timezone-aware UTC datetime.

    Returns None if the value is not a parseable string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Normalize a trailing Z to +00:00 for fromisoformat.
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Format a UTC datetime as ISO 8601 with three fractional digits + Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % millis


def add_hours(dt, hours):
    return dt + timedelta(hours=float(hours))
