"""ISO 8601 parsing for the test-driving clock."""
from datetime import datetime, timezone

import errors


def parse_iso8601(value):
    if not isinstance(value, str):
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 string")
    raw = value.strip()
    # Accept trailing Z as UTC
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        raise errors.invalid_request("to_iso8601 is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
