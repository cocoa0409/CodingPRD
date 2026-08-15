"""Logical clock (PRD §2.4).

The server never falls back to wall-clock time. Startup default is exactly
2026-08-01T00:00:00Z. A BankAdmin moves the clock via POST /_clock/set_current_utc.
"""

from datetime import datetime, timedelta, timezone

_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"


def parse_iso(value):
    """Parse an ISO 8601 timestamp into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset; fractional digits optional.
    Returns None when the value is not a string or cannot be parsed.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt):
    """Format an aware UTC datetime with second precision and a Z suffix."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_z_millis(dt):
    """Format an aware UTC datetime with three fractional digits (PRD §2.5)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def end_of_day(dt):
    """23:59:59Z on the calendar date of dt (inclusive end-of-day convention)."""
    dt = dt.astimezone(timezone.utc)
    return dt.replace(hour=23, minute=59, second=59, microsecond=0)


def add_business_days(start, n):
    """Add n business days (Mon-Fri only), counting from the day AFTER start."""
    current = start.astimezone(timezone.utc)
    remaining = n
    while remaining > 0:
        current = current + timedelta(days=1)
        if current.weekday() < 5:  # Monday=0 .. Friday=4
            remaining -= 1
    return current


def business_days_between(start, end):
    """Number of Mon-Fri days strictly between date(start) and date(end).

    Counting begins the day after start, per the business-day convention.
    A negative span yields 0 (a notice sent in the future is never cooled).
    """
    s = start.astimezone(timezone.utc).date()
    e = end.astimezone(timezone.utc).date()
    if e <= s:
        return 0
    count = 0
    current = s
    while current < e:
        current = current + timedelta(days=1)
        if current.weekday() < 5:
            count += 1
    return count


class LogicalClock:
    """Mutable logical clock; module-level singleton used by the whole app."""

    def __init__(self):
        self._now = parse_iso(_STARTUP_DEFAULT)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt.astimezone(timezone.utc)
        return self._now

    def now_iso(self):
        return iso_z(self._now)

    def now_iso_millis(self):
        return iso_z_millis(self._now)
