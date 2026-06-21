"""Timestamp helpers.

PRD §2.4: created_at / updated_at are ISO 8601 UTC timestamps with three
fractional digits (milliseconds), e.g. "2025-05-24T10:30:00.123Z".
"""
from datetime import datetime, timezone


def parse_iso8601(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Accepts trailing 'Z' and fractional seconds. Raises ValueError on bad input.
    """
    if not isinstance(value, str):
        raise ValueError("datetime must be a string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def format_iso8601(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits + 'Z'."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    # milliseconds precision
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
