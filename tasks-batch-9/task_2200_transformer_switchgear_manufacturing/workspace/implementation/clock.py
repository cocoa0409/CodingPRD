"""Logical clock. PRD 2.10: nothing in this system reads the operating system clock.

The server starts at the fixed default 2026-08-01T00:00:00Z and NEVER falls back
to real wall-clock time.
"""
from datetime import datetime, timezone, timedelta

DEFAULT_INSTANT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_now = DEFAULT_INSTANT


def reset():
    global _now
    _now = DEFAULT_INSTANT


def now():
    return _now


def set_now(dt):
    global _now
    _now = dt


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    d = dt.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (d.microsecond // 1000)) + "Z"


def now_str():
    return fmt(_now)


def parse(value):
    """Parse an ISO-8601 instant. Returns None when unparseable."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        # date-only or other shapes
        for f in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
            try:
                d = datetime.strptime(value.strip(), f)
                break
            except ValueError:
                d = None
        if d is None:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def sec(dt):
    """Truncate to second granularity -- PRD: instants compared at second granularity."""
    if dt is None:
        return None
    return dt.replace(microsecond=0)


def day(dt):
    """Bucket an instant to a whole UTC calendar date."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).date()


def add_calendar_months(dt, months):
    """Calendar-month arithmetic with day-of-month overflow clamped to the last
    day of the target month."""
    y = dt.year + (dt.month - 1 + months) // 12
    m = (dt.month - 1 + months) % 12 + 1
    # last day of target month
    if m == 12:
        nxt = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(y, m + 1, 1, tzinfo=timezone.utc)
    last_day = (nxt - timedelta(days=1)).day
    d = min(dt.day, last_day)
    return dt.replace(year=y, month=m, day=d)
