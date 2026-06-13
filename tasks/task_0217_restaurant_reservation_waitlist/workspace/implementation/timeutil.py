"""Datetime parsing and formatting helpers.

All instants stored and returned are UTC ISO 8601 with three fractional
digits (PRD §2.5, §2.6).
"""
from datetime import datetime, timezone

from errors import err, ERR_VALIDATION


def parse_iso(value, field="datetime"):
    """Parse an ISO 8601 string into a tz-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Naive strings are treated
    as UTC. Raises ERR_VALIDATION on a malformed value.
    """
    if not isinstance(value, str) or not value:
        raise err(ERR_VALIDATION, f"{field} must be an ISO 8601 string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err(ERR_VALIDATION, f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Render a tz-aware datetime as UTC ISO 8601 with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # millisecond precision, always three fractional digits, 'Z' suffix
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
