"""Deterministic-clock / instant arithmetic helpers (PRD §2.6, §1.3).

All clinic-clock and scheduling instants are ISO 8601 UTC. We parse to aware
datetimes for comparison and re-emit with millisecond precision.
"""
from datetime import datetime, timedelta, timezone

from errors import err, ERR_INVALID_REQUEST


def parse_instant(value):
    """Parse an ISO 8601 UTC instant into an aware datetime.

    Accepts a trailing 'Z' or an explicit offset. Raises ERR_INVALID_REQUEST on
    a malformed value.
    """
    if not isinstance(value, str) or not value:
        raise err(ERR_INVALID_REQUEST, "Invalid or missing timestamp")
    raw = value.strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "Malformed ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_instant(dt):
    """Format an aware datetime as ISO 8601 UTC with millisecond precision."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


EPOCH_ISO = "1970-01-01T00:00:00.000Z"
