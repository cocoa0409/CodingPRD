"""Time parsing and comparison helpers."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 string (allowing trailing Z). Returns timezone-aware UTC."""
    if value is None:
        raise ValueError("None is not a valid ISO datetime")
    s = value.strip()
    # Convert trailing 'Z' to '+00:00' for fromisoformat.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(value: str, days: int) -> str:
    """Add `days` to an ISO datetime string and return ISO 8601 UTC w/ ms precision."""
    base = parse_iso(value)
    new = base + timedelta(days=days)
    millis = new.microsecond // 1000
    return new.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def whole_days_between(later_iso: str, earlier_iso: str) -> int:
    """Floor of (later - earlier) in days."""
    later = parse_iso(later_iso)
    earlier = parse_iso(earlier_iso)
    delta = later - earlier
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return 0
    return seconds // 86400


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_valid_iso_date(value: str) -> bool:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def age_years_at(now: datetime, dob_iso: str) -> float:
    """Return age in years as a float (approximate, calendar based)."""
    dob = datetime.strptime(dob_iso, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    delta = now - dob
    return delta.total_seconds() / (365.25 * 86400)
