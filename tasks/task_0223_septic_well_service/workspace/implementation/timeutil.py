"""Timestamp and date helpers.

Timestamps are ISO 8601 UTC with three fractional digits and a trailing Z
(PRD §2.4). Dates are ISO YYYY-MM-DD.
"""
from datetime import datetime, timezone, date


def iso_ms(dt=None):
    """ISO 8601 UTC with milliseconds and trailing Z."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 instant (with optional Z / offset) into tz-aware UTC."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_months(d, months):
    """Add `months` to a date, clamping to end-of-month on overflow."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    # clamp day to last valid day of target month
    day = d.day
    last = _last_day(y, m)
    if day > last:
        day = last
    return date(y, m, day)


def _last_day(year, month):
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    from datetime import timedelta
    return (nxt - timedelta(days=1)).day


def parse_date(s):
    """Parse an ISO YYYY-MM-DD date string into a date object."""
    return datetime.strptime(s, "%Y-%m-%d").date()
