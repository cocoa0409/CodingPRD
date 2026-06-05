"""Datetime parsing/arithmetic for temporal rules (timely filing, appeal
window, bad-debt aging)."""
from datetime import datetime, timezone

import errors


def parse_iso(value, field="timestamp"):
    """Parse an ISO 8601 instant into a tz-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Naive values are treated as
    UTC. Raises ERR_INVALID_REQUEST on a malformed value."""
    if not isinstance(value, str) or value.strip() == "":
        raise errors.invalid_request(f"Field '{field}' must be an ISO 8601 string.")
    raw = value.strip()
    candidate = raw
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        raise errors.invalid_request(f"Field '{field}' is not a valid ISO 8601 instant.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field="date"):
    """Parse a YYYY-MM-DD calendar date into a date object."""
    if not isinstance(value, str) or value.strip() == "":
        raise errors.invalid_request(f"Field '{field}' must be a date string.")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise errors.invalid_request(f"Field '{field}' must be a YYYY-MM-DD date.")


def days_between(later, earlier):
    """Whole-and-fractional days between two tz-aware datetimes (later - earlier)."""
    return (later - earlier).total_seconds() / 86400.0
