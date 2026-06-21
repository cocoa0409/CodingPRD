"""Shared helpers: id minting, timestamp formatting, datetime parsing."""
import uuid
import random
import string
from datetime import datetime, timezone

import clock


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    """Request id beginning with req_ (PRD §2.2)."""
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def iso_now():
    """ISO 8601 UTC timestamp with three fractional digits, from the logical clock."""
    return format_ts(clock.now())


def format_ts(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def format_date(dt):
    """Format a UTC-midnight date as ISO 8601 without fractional seconds.

    PRD §2.4 reserves the three-fractional-digit form for created_at/updated_at
    *timestamps*; date fields (service_date, effective_pickup_date, holiday_date,
    requested_date, period_start/end, due_date, service_start_date) are described
    as a "UTC-midnight date" and render in the canonical midnight form
    YYYY-MM-DDTHH:MM:SSZ.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value):
    """Parse an ISO 8601 string into a timezone-aware UTC datetime.

    Returns None if the value cannot be parsed.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_midnight(dt):
    """Truncate a timezone-aware datetime to UTC midnight."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)
