"""Timestamp formatting/parsing per PRD: ISO 8601 UTC, three fractional digits."""

from datetime import datetime, timezone
import errors


def fmt(dt):
    """datetime -> '2026-08-01T00:00:00.000Z'"""
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_dt(value, field="timestamp"):
    """Parse an ISO 8601 string; naive values are treated as UTC."""
    if not isinstance(value, str) or not value.strip():
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, f"Field '{field}' must be an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.err(errors.ERR_INVALID_REQUEST, 400, f"Field '{field}' is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
