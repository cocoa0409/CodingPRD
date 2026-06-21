"""Facility logical-clock parsing and calendar-day arithmetic.

All day arithmetic for overstay, proration, abandonment, and suspension is
performed in the facility's time_zone (PRD §2.6).
"""
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None


def parse_iso(value):
    """Parse an ISO 8601 instant (with optional 'Z' / offset) to aware UTC dt.

    Returns None when the value is not a valid ISO 8601 instant.
    """
    if not isinstance(value, str) or not value:
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _tz(time_zone):
    if not time_zone or ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(time_zone)
    except Exception:
        return timezone.utc


def local_date(instant, time_zone):
    """Return the calendar date (date object) of an aware UTC instant in tz."""
    return instant.astimezone(_tz(time_zone)).date()


def calendar_days_between(start_instant, end_instant, time_zone):
    """Whole calendar days = local_date(end) - local_date(start). May be negative."""
    d0 = local_date(start_instant, time_zone)
    d1 = local_date(end_instant, time_zone)
    return (d1 - d0).days


def add_days(instant, days):
    return instant + timedelta(days=days)


def to_iso_z(instant):
    """Render an aware instant as ISO 8601 UTC with 3 fractional digits."""
    dt = instant.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
