"""Shared low-level helpers: id generation, timestamp formatting, datetime parsing."""
import random
import re
import string
import uuid
from datetime import datetime, timezone


def new_id():
    """Server-minted id: a bare UUID4 string with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    """meta.api_request_id: a random alphanumeric string starting with 'req_' (PRD §2.2)."""
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def iso(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits and a 'Z'
    suffix, e.g. 2025-05-24T10:30:00.123Z (PRD §2.2 / §2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    # milliseconds = first three fractional digits
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (".%03dZ" % ms)


_DT_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")


def parse_dt(value):
    """Parse an ISO 8601 datetime string into a timezone-aware UTC datetime.

    Returns None if the value is not a parseable datetime string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Normalise a trailing Z to +00:00 for fromisoformat.
    candidate = s
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        # Fall back to a couple of common explicit formats.
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(dt, months):
    """Add a number of calendar months to a datetime (PRD §3.1 valid_until)."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp day to the last valid day of the target month.
    day = dt.day
    import calendar

    last_day = calendar.monthrange(year, month)[1]
    if day > last_day:
        day = last_day
    return dt.replace(year=year, month=month, day=day)


def floor_days(later, earlier):
    """Whole number of days between two instants, floored (PRD §2.8 / §3.6).

    Python's timedelta.days is already floored toward negative infinity, which
    is exactly the floor semantics the PRD specifies.
    """
    return (later - earlier).days
