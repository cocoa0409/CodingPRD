"""Logical clock (PRD §2.4) and calendar arithmetic (PRD §2.8).

The server never falls back to wall-clock time. Startup default is exactly
2026-08-01T00:00:00Z. A SystemAdmin moves the clock via
POST /_clock/set_current_utc. All business timestamps read this clock.

Calendar-day arithmetic adds whole 86,400-second days directly to a base
instant. Business-day arithmetic counts days beginning the day AFTER the base
date, skipping Saturdays, Sundays, and every registered HolidayObservance
observance_date, landing at the same time of day as the base instant.
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


def iso_ms(dt):
    """Format an aware UTC datetime with three fractional digits (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def business_due(base, n, holiday_dates):
    """business_due(date(base), n) at time-of-day(base).

    Counts n days starting from the day AFTER date(base), skipping Saturdays,
    Sundays, and every date string (YYYY-MM-DD) in holiday_dates.
    """
    current = base.astimezone(timezone.utc)
    remaining = n
    while remaining > 0:
        current = current + timedelta(days=1)
        if current.weekday() < 5 and current.date().isoformat() not in holiday_dates:
            remaining -= 1
    return current


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
        return iso_ms(self._now)
