"""Logical server clock.

The current UTC instant defaults to real wall-clock time, but can be pinned to a
specific instant via POST /_clock/set_current_utc so that due-date / default
timing can be driven deterministically by tests.
"""
import datetime


class Clock:
    def __init__(self):
        # When None, fall back to real wall clock.
        self._pinned = None

    def now(self):
        if self._pinned is not None:
            return self._pinned
        return datetime.datetime.now(datetime.timezone.utc)

    def set(self, dt):
        self._pinned = dt

    def reset(self):
        self._pinned = None


clock = Clock()


def parse_iso8601(value):
    """Parse an ISO 8601 string into an aware UTC datetime. Raises ValueError on failure."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    # Python 3.9 fromisoformat does not accept a trailing 'Z'; normalize it.
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    return dt


def format_iso8601(dt):
    """Format an aware datetime as ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(datetime.timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % millis


def add_months(dt, months):
    """Return dt advanced by the given number of calendar months (UTC)."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp the day to the last valid day of the target month.
    day = dt.day
    # Find last day of target month.
    if month == 12:
        next_month_first = datetime.datetime(year + 1, 1, 1, tzinfo=datetime.timezone.utc)
    else:
        next_month_first = datetime.datetime(year, month + 1, 1, tzinfo=datetime.timezone.utc)
    last_day = (next_month_first - datetime.timedelta(days=1)).day
    if day > last_day:
        day = last_day
    return dt.replace(year=year, month=month, day=day)
