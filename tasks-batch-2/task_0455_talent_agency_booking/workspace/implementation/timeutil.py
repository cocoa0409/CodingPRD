"""Datetime parsing and temporal helpers built on the logical clock."""
from datetime import datetime, timezone, date, timedelta

from errors import ApiError


def parse_dt(value):
    """Parse an ISO-8601 datetime/date string into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Returns None if value is not
    a parseable string (caller decides whether that is an error).
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Normalize trailing Z to +00:00 for fromisoformat
    candidate = s
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        # Try a plain date (YYYY-MM-DD)
        try:
            d = date.fromisoformat(s)
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_dt(value):
    dt = parse_dt(value)
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST")
    return dt


def to_date(dt):
    """Calendar date (UTC) of an aware datetime."""
    return dt.astimezone(timezone.utc).date()


def inclusive_day_span(start_dt, end_dt):
    """Inclusive day count between two datetimes by calendar date.

    (end_date - start_date) + 1, counting both endpoints.
    """
    return (to_date(end_dt) - to_date(start_dt)).days + 1


def now_dt(db):
    """The current logical-clock instant as an aware UTC datetime."""
    dt = parse_dt(db.clock)
    if dt is None:
        dt = parse_dt("2026-01-01T00:00:00Z")
    return dt


def normalize_clock_iso(dt):
    """Render a datetime as an ISO-8601 UTC string for the clock echo."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
