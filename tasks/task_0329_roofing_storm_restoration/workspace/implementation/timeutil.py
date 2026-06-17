"""Datetime parsing/formatting helpers.

Timestamps are ISO 8601 UTC with three fractional digits (PRD §2.4).
"""
from datetime import datetime, timezone


def parse_iso8601(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None if the value is not a parseable ISO 8601 datetime.
    Accepts a trailing 'Z' and explicit offsets; naive values are treated UTC.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Python's fromisoformat (3.11+) accepts 'Z', but normalize for older too.
    candidate = s
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def now_iso(dt=None):
    """Format an aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # millisecond precision, trailing 'Z'
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
