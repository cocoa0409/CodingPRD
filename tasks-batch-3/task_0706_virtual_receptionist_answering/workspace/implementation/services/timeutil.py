"""Datetime parsing for appointment/slot intervals (ISO 8601 UTC)."""
from datetime import datetime, timezone

import errors


def parse_dt(value, field):
    if not isinstance(value, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.err(errors.ERR_INVALID_REQUEST, f"{field} is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_epoch(value, field):
    return int(parse_dt(value, field).timestamp())
