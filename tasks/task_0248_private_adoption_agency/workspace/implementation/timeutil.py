"""UTC datetime parsing/formatting and temporal helpers (PRD §2.9)."""
from datetime import datetime, timedelta, timezone


def parse_iso(value):
    """Parse an ISO 8601 datetime string into a timezone-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Returns None if not a string
    or not parseable.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Normalize trailing Z to +00:00 for fromisoformat (Py3.9 lacks Z support).
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def format_iso(dt):
    """Format a timezone-aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def add_days(dt, days):
    return dt + timedelta(days=days)


def business_days_deadline(signed_at, business_days):
    """Compute the BUSINESS_DAYS revocation deadline (calculation revocation_deadline).

    Counting begins on the calendar day AFTER signed_at. Step one calendar day at
    a time; Mon-Fri (UTC weekday 0..4) each decrement the remaining count by one,
    Sat/Sun are skipped. The deadline is 23:59:59.000Z of the day on which the
    count reaches zero.
    """
    remaining = business_days
    cur = signed_at
    while remaining > 0:
        cur = cur + timedelta(days=1)
        if cur.weekday() <= 4:  # Mon(0)..Fri(4)
            remaining -= 1
    return cur.replace(hour=23, minute=59, second=59, microsecond=0)
