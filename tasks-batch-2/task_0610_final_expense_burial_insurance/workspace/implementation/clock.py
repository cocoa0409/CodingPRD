"""The logical clock (PRD §2.4).

The server never reads wall-clock time. A single logical clock holds the
current instant; it reads the fixed startup default 2026-01-01T00:00:00Z
before any call is made. All time-sensitive rules are measured against it.

Timestamps minted for resource fields (created_at, updated_at, issue_date,
posted_date, ...) are the logical clock value, formatted ISO 8601 UTC with
three fractional digits.  The response envelope's api_request_timestamp is
also produced here in that format.
"""
from datetime import datetime, timezone

_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"now": _DEFAULT}


def reset():
    _state["now"] = _DEFAULT


def get_now():
    """Return the current logical clock as a timezone-aware datetime."""
    return _state["now"]


def set_now(dt):
    _state["now"] = dt


def now_iso_millis():
    """Format the current logical clock as ISO 8601 UTC with 3 fractional digits."""
    return format_iso_millis(_state["now"])


def format_iso_millis(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-01-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime (date or datetime), returning a UTC datetime.

    Accepts a trailing 'Z' and bare dates (YYYY-MM-DD, treated as midnight UTC).
    Returns None on failure.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    candidate = text
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        # Try a bare date.
        try:
            dt = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
