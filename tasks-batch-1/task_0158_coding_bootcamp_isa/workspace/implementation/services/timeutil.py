"""Datetime parsing for time-gated logic.

The server keeps a single logical UTC clock (PRD §2.10). Date/datetime inputs are
ISO 8601 strings; we parse them into aware UTC datetimes for comparison.
"""
from datetime import datetime, timezone, date

import errors


def parse_dt(value, field_name="datetime"):
    if not isinstance(value, str):
        raise errors.invalid_request(f"{field_name} must be an ISO 8601 string")
    raw = value.strip()
    s = raw
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Try plain date (YYYY-MM-DD)
        try:
            d = date.fromisoformat(raw)
            dt = datetime(d.year, d.month, d.day)
        except ValueError:
            raise errors.invalid_request(f"{field_name} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_date(dt):
    """Calendar date (UTC) of an aware datetime — for closed/half-open day math."""
    return dt.date()
