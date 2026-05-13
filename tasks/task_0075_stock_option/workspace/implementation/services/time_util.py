"""Plan-clock time utilities. All time math uses the plan's logical clock."""

from datetime import datetime, timezone, timedelta


def parse_iso(s):
    """Parse an ISO-8601 timestamp into a timezone-aware datetime (UTC)."""
    if s is None:
        return None
    if isinstance(s, datetime):
        if s.tzinfo is None:
            return s.replace(tzinfo=timezone.utc)
        return s.astimezone(timezone.utc)
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if not txt:
        return None
    # Replace trailing Z with +00:00 for fromisoformat
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso(dt):
    """Format a datetime to ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if isinstance(dt, str):
        # Already formatted
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def server_now():
    return datetime.now(timezone.utc)


def add_seconds(dt, seconds):
    return dt + timedelta(seconds=int(seconds))


def add_days(dt, days):
    return dt + timedelta(days=int(days))


def add_months(dt, months):
    """Add an integer number of (calendar) months to dt; clamp day-of-month."""
    months = int(months)
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    # Clamp day
    from calendar import monthrange
    last_day = monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def floor_months_between(start, end):
    """Whole months elapsed between start and end. Negative if end<start (return 0)."""
    if end < start:
        return 0
    years = end.year - start.year
    months = end.month - start.month
    total = years * 12 + months
    # Subtract one if end day-of-month / time-of-day is before start's
    if (end.day, end.hour, end.minute, end.second, end.microsecond) < \
       (start.day, start.hour, start.minute, start.second, start.microsecond):
        total -= 1
    return max(0, total)


def days_between(start, end):
    """Whole days elapsed between two datetimes (floor of the delta in days)."""
    delta = end - start
    # delta.days is already floored toward negative infinity in Python
    return delta.days
