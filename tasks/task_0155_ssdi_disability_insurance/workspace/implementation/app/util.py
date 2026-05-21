"""Date/time helpers and miscellaneous utilities."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional

from app.errors import bad_request


def new_uuid() -> str:
    """Generate a UUID4 string (no type prefix — PRD §2.4)."""
    return str(uuid.uuid4())


def iso_utc(dt: datetime) -> str:
    """Render a UTC datetime as ISO 8601 with 3 fractional digits and Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso_datetime(raw: str, field_name: str = "datetime") -> datetime:
    """Parse an ISO 8601 datetime string into a UTC-aware datetime."""
    if not isinstance(raw, str) or not raw:
        raise bad_request(f"{field_name} must be a non-empty ISO 8601 string")
    s = raw.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except Exception:
        raise bad_request(f"{field_name} is not a valid ISO 8601 datetime: {raw}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def parse_iso_date(raw: str, field_name: str = "date") -> date:
    """Parse an ISO 8601 date (YYYY-MM-DD) or datetime, returning a date()."""
    if not isinstance(raw, str) or not raw:
        raise bad_request(f"{field_name} must be a non-empty ISO 8601 date string")
    s = raw.strip()
    # Accept either pure date or datetime; coerce to date.
    try:
        if "T" in s or " " in s:
            return parse_iso_datetime(s, field_name).date()
        return date.fromisoformat(s)
    except Exception:
        raise bad_request(f"{field_name} is not a valid ISO 8601 date: {raw}")


def date_to_iso(d: date) -> str:
    """Render a date as a plain ISO date string (YYYY-MM-DD)."""
    if isinstance(d, datetime):
        d = d.date()
    return d.isoformat()


def floor_age_years(reference: date, dob: date) -> int:
    """Integer years between two dates, floor (i.e. years of age)."""
    years = reference.year - dob.year
    if (reference.month, reference.day) < (dob.month, dob.day):
        years -= 1
    return years


def add_months(d: date, months: int) -> date:
    """Add `months` whole calendar months to a date; clamp day-of-month."""
    if isinstance(d, datetime):
        d = d.date()
    total = d.month - 1 + months
    new_year = d.year + total // 12
    new_month = total % 12 + 1
    # Day clamp: shrink to last day of month if needed.
    import calendar
    last_day = calendar.monthrange(new_year, new_month)[1]
    new_day = min(d.day, last_day)
    return date(new_year, new_month, new_day)


def first_day_of_month(d: date) -> date:
    if isinstance(d, datetime):
        d = d.date()
    return date(d.year, d.month, 1)


def month_diff(later: date, earlier: date) -> int:
    """Number of full calendar months from earlier (inclusive) to later (exclusive)."""
    if isinstance(later, datetime):
        later = later.date()
    if isinstance(earlier, datetime):
        earlier = earlier.date()
    return (later.year - earlier.year) * 12 + (later.month - earlier.month)
