"""Helpers for the deterministic logical clock and date arithmetic.

The District.current_date is the authoritative present for compliance math.
Format: ISO 8601 UTC with three fractional digits (e.g. 2025-01-01T00:00:00.000Z).
"""

from datetime import datetime, timedelta, timezone


CLOCK_EPOCH = "2025-01-01T00:00:00.000Z"


def parse_dt(value: str) -> datetime:
    """Parse an ISO 8601 datetime/date string into a UTC datetime."""
    if value is None:
        raise ValueError("datetime is None")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Allow bare date strings — interpret as midnight UTC.
        dt = datetime.fromisoformat(s + "T00:00:00+00:00")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def format_dt(dt: datetime) -> str:
    """Render datetime as ISO 8601 UTC with three fractional digits, Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def advance_days(value: str, by_days: int) -> str:
    dt = parse_dt(value) + timedelta(days=by_days)
    return format_dt(dt)


def days_between(later: str, earlier: str) -> int:
    """Integer day difference: (later - earlier).days using date-only semantics in UTC."""
    a = parse_dt(later).date()
    b = parse_dt(earlier).date()
    return (a - b).days


def add_years_same_md(value: str, years: int) -> str:
    """Return value advanced by N calendar years, preserving month/day.

    Feb 29 + N years where the target year is not a leap year falls back to Feb 28
    (a reasonable convention; cases in this domain anchor to non-leap-day dates).
    """
    dt = parse_dt(value)
    try:
        new = dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 in a non-leap year — clamp to Feb 28.
        new = dt.replace(year=dt.year + years, day=28)
    return format_dt(new)


def date_at_or_before(d_value: str, ref_value: str) -> bool:
    """True iff d_value <= ref_value (date-only comparison in UTC)."""
    return parse_dt(d_value).date() <= parse_dt(ref_value).date()


def date_at_or_after(d_value: str, ref_value: str) -> bool:
    """True iff d_value >= ref_value (date-only comparison in UTC)."""
    return parse_dt(d_value).date() >= parse_dt(ref_value).date()


def datetime_strictly_before(a_value: str, b_value: str) -> bool:
    return parse_dt(a_value) < parse_dt(b_value)


def datetime_at_or_before(a_value: str, b_value: str) -> bool:
    return parse_dt(a_value) <= parse_dt(b_value)
