"""Date / datetime parsing helpers for ISO 8601 inputs.

Used for due_date, period_start/period_end, as_of_date. Inputs are accepted
as ISO 8601 strings (date or datetime). A value that cannot be parsed is a
bad type for that field.
"""
from datetime import datetime, timezone, date


def parse_dt(value):
    """Parse an ISO 8601 date or datetime string into an aware UTC datetime.

    Returns None on failure.
    """
    if not isinstance(value, str) or not value:
        return None
    s = value.strip()
    # Normalize trailing Z to +00:00 for fromisoformat.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Try plain date.
        try:
            d = date.fromisoformat(value.strip())
            dt = datetime(d.year, d.month, d.day)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_utc():
    return datetime.now(timezone.utc)


def whole_days(start_dt, end_dt):
    """Whole number of days between two datetimes (end - start), half-open."""
    delta = end_dt - start_dt
    return delta.days
