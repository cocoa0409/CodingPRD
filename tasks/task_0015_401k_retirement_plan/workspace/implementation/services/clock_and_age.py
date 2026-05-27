"""Clock-driven helpers: years_of_service, age computation."""

from __future__ import annotations

from datetime import datetime, timezone

import db


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 timestamp/date into a tz-aware UTC datetime.

    Accepts dates ('2026-01-01'), datetimes with/without timezone, and the
    'Z' suffix.
    """
    if not isinstance(s, str):
        raise ValueError("expected ISO 8601 string")
    text = s.strip()
    # Python's fromisoformat in 3.11+ accepts 'Z'. Fall back for safety.
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        # Date-only fallback.
        dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def years_of_service(hire_date_iso: str) -> int:
    """floor((current_clock - hire_date).days / 365)."""
    now = db.get_clock()
    hire = parse_iso(hire_date_iso)
    delta_days = (now - hire).days
    if delta_days < 0:
        return 0
    return delta_days // 365


def age_today_years(date_of_birth_iso: str) -> int:
    """floor((current_clock - dob).days / 365). Whole years per §2.5 integer rule."""
    now = db.get_clock()
    dob = parse_iso(date_of_birth_iso)
    delta_days = (now - dob).days
    if delta_days < 0:
        return 0
    return delta_days // 365


def age_at_year_end(date_of_birth_iso: str, year: int) -> int:
    """floor((Dec 31 of `year` - dob).days / 365)."""
    dob = parse_iso(date_of_birth_iso)
    year_end = datetime(year, 12, 31, tzinfo=timezone.utc)
    delta_days = (year_end - dob).days
    if delta_days < 0:
        return 0
    return delta_days // 365
