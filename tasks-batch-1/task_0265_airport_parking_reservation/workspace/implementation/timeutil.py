"""Datetime parsing/formatting helpers (ISO 8601 UTC, three fractional digits)."""
from datetime import datetime, timezone

from errors import err


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime.

    Raises ERR_VALIDATION on malformed input.
    """
    if not isinstance(value, str) or not value:
        raise err("ERR_VALIDATION", "Invalid datetime value.")
    raw = value.strip()
    # Normalise trailing 'Z' to +00:00 for fromisoformat (Python 3.9).
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        raise err("ERR_VALIDATION", "Malformed ISO 8601 datetime.")
    if dt.tzinfo is None:
        # Treat naive datetimes as UTC.
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def format_iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
