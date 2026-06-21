"""Timestamp / date helpers.

PRD §2.4: timestamps are ISO 8601 UTC with exactly three fractional digits
(milliseconds), e.g. "2025-05-24T10:30:00.123Z".
"""

from datetime import datetime, timezone, date


def now_iso(dt=None):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits
    and a trailing Z."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 instant (with or without trailing Z / offset) into an
    aware UTC datetime. Returns None on failure."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse a YYYY-MM-DD calendar date. Returns a date or None."""
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def add_days(dt, days):
    """Add a whole number of days to an aware datetime."""
    from datetime import timedelta
    return dt + timedelta(days=days)


def add_months(d, months):
    """Add a whole number of months to a calendar date, clamping the day to the
    last valid day of the resulting month."""
    if isinstance(d, datetime):
        d = d.date()
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    # clamp the day
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    day = min(d.day, last_day)
    return date(year, month, day)


def clock_date(dt):
    """The calendar date of an aware UTC datetime."""
    return dt.astimezone(timezone.utc).date()
