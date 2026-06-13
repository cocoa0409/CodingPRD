"""Datetime parsing/formatting helpers.

All timestamps in this system are ISO 8601 UTC with exactly three fractional
digits, e.g. "2025-05-24T10:30:00.123Z". Datetime arithmetic is performed in
whole seconds (epoch seconds), with 86400 seconds per day.
"""
from datetime import datetime, timezone

SECONDS_PER_DAY = 86400
EPOCH_ISO = "1970-01-01T00:00:00.000Z"


def now_iso():
    """Wall-clock now formatted for response meta (api_request_timestamp)."""
    return format_iso(datetime.now(timezone.utc))


def format_iso(dt):
    """Format a tz-aware datetime as ISO 8601 UTC with millisecond precision."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # millisecond precision, trailing 'Z'
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 datetime string into a tz-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Returns None if unparseable.
    Also accepts bare date "YYYY-MM-DD" (treated as midnight UTC).
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    candidate = s
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        # try bare date
        try:
            dt = datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a bare ISO date YYYY-MM-DD; returns a date or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None


def epoch_seconds(dt):
    """Whole epoch seconds for a tz-aware datetime."""
    return int(dt.timestamp())


def iso_to_epoch(value):
    """ISO string -> epoch seconds (int), or None if unparseable."""
    dt = parse_iso(value)
    if dt is None:
        return None
    return epoch_seconds(dt)


def epoch_to_iso(seconds):
    """Epoch seconds (int) -> ISO 8601 UTC millisecond string."""
    dt = datetime.fromtimestamp(int(seconds), tz=timezone.utc)
    return format_iso(dt)


def normalize_iso(value):
    """Re-emit any parseable ISO datetime in canonical millisecond-UTC form."""
    dt = parse_iso(value)
    if dt is None:
        return value
    return format_iso(dt)


def add_days_iso(anchor_iso, days):
    """Add whole days (86400s each) to an ISO timestamp; return ISO string."""
    base = iso_to_epoch(anchor_iso)
    return epoch_to_iso(base + int(days) * SECONDS_PER_DAY)
