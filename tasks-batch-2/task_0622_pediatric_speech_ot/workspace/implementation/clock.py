"""Logical clock and ISO 8601 time helpers (PRD §2.11)."""

from datetime import datetime, timezone, date

# PRD §2.11: At startup the logical clock reads exactly 2026-01-01T00:00:00Z,
# and before any clock-setting call it holds that default and never falls back
# to real time.
DEFAULT_CLOCK = "2026-01-01T00:00:00Z"


class Clock:
    def __init__(self):
        self._dt = parse_iso(DEFAULT_CLOCK)

    def now(self):
        """Current logical UTC time as a timezone-aware datetime."""
        return self._dt

    def now_iso(self):
        """Current logical UTC time as ISO 8601 with three fractional digits."""
        return format_iso(self._dt)

    def set(self, iso_string):
        self._dt = parse_iso(iso_string)
        return self._dt


def parse_iso(value):
    """Parse an ISO 8601 datetime (or date) into a timezone-aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    # Accept a trailing Z as UTC.
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO date (YYYY-MM-DD) into a datetime.date."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    return date.fromisoformat(value.strip())


def format_iso(dt):
    """Format a timezone-aware UTC datetime as ISO 8601 with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def whole_months_between(dob, ref_dt):
    """Whole number of months between a date_of_birth (date) and a reference datetime.

    PRD §3.1: age_months_at_intake is the whole number of months between
    date_of_birth and the moment of creation under the logical clock.
    """
    ref = ref_dt.astimezone(timezone.utc)
    months = (ref.year - dob.year) * 12 + (ref.month - dob.month)
    # If the day-of-month hasn't been reached yet in the reference month,
    # the final month is not yet whole.
    if ref.day < dob.day:
        months -= 1
    return months


def whole_minutes_between(start_dt, end_dt):
    """Whole minutes between two datetimes."""
    delta = end_dt - start_dt
    return int(delta.total_seconds() // 60)


def week_of(dt):
    """The Monday-00:00:00Z at or before the instant (ISO week start)."""
    dt = dt.astimezone(timezone.utc)
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    # weekday(): Monday == 0
    monday = midnight.fromordinal(midnight.toordinal() - midnight.weekday())
    return monday.replace(tzinfo=timezone.utc)
