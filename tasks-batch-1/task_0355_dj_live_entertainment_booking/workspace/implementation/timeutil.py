"""Timestamp formatting and ISO 8601 parsing helpers."""
from datetime import datetime, timezone

from errors import invalid_request


def iso_now(dt):
    """Format a timezone-aware datetime as ISO 8601 UTC with three fractional
    digits and a trailing 'Z'."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value, field="timestamp"):
    """Parse an ISO 8601 UTC timestamp into a timezone-aware datetime.

    Accepts a trailing 'Z' or an explicit offset. Naive datetimes are treated
    as UTC. Raises ERR_INVALID_REQUEST on malformed input.
    """
    if not isinstance(value, str) or not value.strip():
        raise invalid_request(f"{field} must be an ISO 8601 datetime string")
    raw = value.strip()
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        raise invalid_request(f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
