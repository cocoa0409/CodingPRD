"""Datetime parsing / formatting for the facility clock and UTC instants.

All facility-clock and entity timestamps are ISO 8601 UTC. BUD arithmetic is in
whole days. We parse to aware datetimes for comparison and re-format with three
fractional digits to keep output stable.
"""
from datetime import datetime, timedelta, timezone

from errors import ApiError


def parse_iso(value, error_id="ERR_INVALID_REQUEST"):
    """Parse an ISO 8601 string into an aware UTC datetime. Raises ApiError on bad input."""
    if not isinstance(value, str):
        raise ApiError(error_id, "Invalid datetime value")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        raise ApiError(error_id, "Invalid ISO 8601 datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Format an aware datetime to ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_days(dt, days):
    return dt + timedelta(days=days)


EPOCH_ISO = "1970-01-01T00:00:00.000Z"
