"""ISO 8601 UTC time utilities (PRD §2.4 / §2.6)."""

from datetime import datetime, timezone, timedelta

from core.errors import raise_error


def iso_format(dt: datetime) -> str:
    """ISO 8601 UTC with 3 fractional digits and trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s, field="value"):
    """Parse ISO 8601 UTC datetime; accept trailing Z or offset."""
    if not isinstance(s, str) or not s.strip():
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' must be a non-empty ISO 8601 string")
    raw = s.strip()
    # Python's fromisoformat accepts +00:00 but not Z; normalize.
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def parse_iso_date(s, field="value"):
    """Parse YYYY-MM-DD as midnight UTC date."""
    if not isinstance(s, str) or not s.strip():
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' must be a non-empty ISO 8601 date string")
    try:
        d = datetime.strptime(s.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise_error("ERR_INVALID_REQUEST", f"Field '{field}' is not a valid YYYY-MM-DD date")
    return d


def days(n: int) -> timedelta:
    """N days expressed as exactly N * 86400 seconds (PRD §2.6)."""
    return timedelta(seconds=int(n) * 86400)
