"""Timestamp parsing and formatting helpers.

PRD §2.4: created_at/updated_at are ISO 8601 UTC timestamps with three
fractional digits. PRD §2.2: api_request_timestamp same format.
"""
from datetime import datetime, timezone

from errors import err


def iso_z(dt):
    """Format a timezone-aware datetime as ISO 8601 UTC with exactly three
    fractional digits and a trailing Z (e.g. 2025-05-24T10:30:00.123Z)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string into a timezone-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Naive timestamps are treated
    as UTC. Raises ERR_INVALID_REQUEST on a malformed value.
    """
    if not isinstance(value, str) or not value:
        raise err("ERR_INVALID_REQUEST", "invalid datetime")
    raw = value.strip()
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", "invalid datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
