"""Timestamp formatting + ISO 8601 parsing helpers.

PRD §2.2 / §2.4: timestamps are ISO 8601 UTC with three fractional digits,
e.g. "2025-05-24T10:30:00.123Z".
"""
from datetime import datetime, timezone, date


def iso_now_ms(dt=None):
    """Format an aware/naive datetime as ISO 8601 UTC with millisecond
    precision and a trailing 'Z'."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}".format(dt.microsecond // 1000) + "Z"


def parse_iso(value):
    """Parse an ISO 8601 string (date or datetime, with or without 'Z' /
    offset) into an aware UTC datetime. Raises ValueError on bad input."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if not s:
        raise ValueError("empty")
    # Date-only form (e.g. "2025-05-20")
    if "T" not in s and " " not in s:
        d = date.fromisoformat(s)
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    iso = s
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
