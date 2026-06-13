"""Date/time parsing and cutoff/delivery-day arithmetic.

All cutoff, delivery-day, and freshness comparisons read a distributor's
logical `current_utc` (PRD §2.9), never wall-clock time. Times are ISO 8601
UTC strings. requested_delivery_date is UTC midnight of a calendar date.
"""
from datetime import datetime, timedelta, timezone

import errors


def parse_iso(value, field="datetime"):
    """Parse an ISO 8601 string into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Raises ERR_INVALID_REQUEST on
    a malformed value.
    """
    if value is None or not isinstance(value, str) or value.strip() == "":
        raise errors.invalid_request("Field '%s' must be an ISO 8601 datetime." % field)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.invalid_request("Field '%s' is not a valid ISO 8601 datetime." % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def day_of_week_monday0(dt):
    """Day of week as 0=Monday .. 6=Sunday (matches Route.delivery_dow)."""
    # Python's weekday(): Monday is 0, Sunday is 6 — exactly the scheme we want.
    return dt.weekday()


def midnight_utc(dt):
    """UTC midnight (00:00:00) of the calendar date of dt."""
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def whole_day_distance(date_a, date_b):
    """Absolute whole-day distance between two delivery dates (UTC midnights)."""
    a = midnight_utc(date_a)
    b = midnight_utc(date_b)
    delta = a - b
    return abs(delta.days)


def cutoff_instant(delivery_date, cutoff_lead_hours):
    """Delivery date's midnight minus cutoff_lead_hours (PRD §3.3)."""
    return midnight_utc(delivery_date) - timedelta(hours=cutoff_lead_hours)
