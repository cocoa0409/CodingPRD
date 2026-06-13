"""Server-simulated wall clock and timestamp/date helpers.

The system operates against a simulated clock (PRD §2.4). When the clock has
not been set, it defaults to actual UTC now. Setting it via the test-driving
endpoint pins it to a fixed instant.
"""
from datetime import datetime, timezone, date


# Module-level simulated clock state. None => use real wall-clock UTC.
_simulated_utc = None  # datetime (aware, UTC)


def reset():
    """Reset the simulated clock to unset (real time)."""
    global _simulated_utc
    _simulated_utc = None


def set_current_utc(dt):
    """Pin the simulated clock to an aware UTC datetime."""
    global _simulated_utc
    _simulated_utc = dt.astimezone(timezone.utc)


def now():
    """Return the current simulated instant as an aware UTC datetime."""
    if _simulated_utc is not None:
        return _simulated_utc
    return datetime.now(timezone.utc)


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (milliseconds)."""
    return format_iso(now())


def current_date():
    """The simulated clock's calendar date (UTC)."""
    return now().date()


def format_iso(dt):
    """Format an aware datetime as ISO 8601 UTC with millisecond precision."""
    dt = dt.astimezone(timezone.utc)
    # millisecond precision, trailing Z
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso8601(value):
    """Parse an ISO 8601 instant (with optional Z / offset) into aware UTC dt.

    Returns None on failure.
    """
    if not isinstance(value, str):
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


def parse_date(value):
    """Parse a YYYY-MM-DD ISO date string. Returns a date or None."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except (ValueError, TypeError):
        return None


def add_months(d, months):
    """Add a number of calendar months to a date, clamping day-of-month."""
    if isinstance(d, str):
        d = parse_date(d)
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    # clamp day to valid range for the target month
    day = d.day
    # find last valid day of target month
    if month == 12:
        next_month_first = date(year + 1, 1, 1)
    else:
        next_month_first = date(year, month + 1, 1)
    last_day = (next_month_first - date(year, month, 1)).days
    if day > last_day:
        day = last_day
    return date(year, month, day)
