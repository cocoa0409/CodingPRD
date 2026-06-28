"""Time / calendar helpers for the logical clock.

Settlement and margin deadlines are expressed in *business days* (Mon-Fri).
Dividend windows are in *calendar days*. All instants are tz-aware UTC.
Dates are derived from the logical clock's calendar date (PRD §2.5, §3)."""
from datetime import datetime, timedelta, timezone


def parse_iso(s):
    """Parse an ISO 8601 instant (accepts trailing Z) to a tz-aware UTC datetime."""
    if isinstance(s, datetime):
        dt = s
    else:
        txt = s.strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """Render a tz-aware datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def date_floor(dt):
    """Midnight UTC of the instant's calendar date."""
    return datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc)


def is_business_day(d):
    return d.weekday() < 5  # 0=Mon .. 4=Fri


def add_business_days(dt, n):
    """Return the instant n business days after dt's calendar date, at 00:00 UTC.
    Counts only Mon-Fri; weekends are skipped."""
    d = date_floor(dt)
    added = 0
    while added < n:
        d = d + timedelta(days=1)
        if is_business_day(d):
            added += 1
    return d


def add_calendar_days(dt, n):
    """Return the instant n calendar days after dt (preserving time-of-day)."""
    return dt + timedelta(days=n)


def trailing_business_window_start(clock, business_days):
    """Earliest date (00:00 UTC) included in a trailing window of `business_days`
    business days counted back from the clock's calendar date, inclusive of both
    ends (so business_days=5 spans 5 business days: today and 4 prior bdays)."""
    d = date_floor(clock)
    # walk back until we've counted `business_days` business days (inclusive)
    counted = 0
    cur = d
    last = d
    while counted < business_days:
        if is_business_day(cur):
            counted += 1
            last = cur
            if counted == business_days:
                break
        cur = cur - timedelta(days=1)
    return last
