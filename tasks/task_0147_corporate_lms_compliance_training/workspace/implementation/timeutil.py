"""Logical-clock time arithmetic, all in UTC.

All times are ISO 8601 UTC strings (three fractional digits, trailing 'Z') in
the store. These helpers parse, format, and do the date math the PRD requires:
add days (due dates), add months (recurrence / certificate expiry), and compute
whole floored days_overdue.
"""

from datetime import datetime, timedelta, timezone

from db import fmt_ts


def parse_iso(s):
    """Parse an ISO 8601 instant into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset; treats naive as UTC.
    """
    if s is None:
        return None
    if isinstance(s, datetime):
        dt = s
    else:
        text = s.strip()
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(iso_str, days):
    dt = parse_iso(iso_str)
    return fmt_ts(dt + timedelta(days=int(days)))


def add_months(iso_str, months):
    """Add a whole number of calendar months, clamping day-of-month overflow."""
    dt = parse_iso(iso_str)
    months = int(months)
    total = (dt.year * 12 + (dt.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    # clamp day to the last valid day of the target month
    day = dt.day
    last_day = _last_day_of_month(year, month)
    if day > last_day:
        day = last_day
    new_dt = dt.replace(year=year, month=month, day=day)
    return fmt_ts(new_dt)


def _last_day_of_month(year, month):
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return (nxt - timedelta(days=1)).day


def days_overdue(now_iso, due_iso):
    """Whole floored days from due_date to now (negative/zero when not overdue)."""
    now = parse_iso(now_iso)
    due = parse_iso(due_iso)
    delta = now - due
    total_seconds = delta.total_seconds()
    # floor toward negative infinity over the 86400s/day measure
    import math
    return int(math.floor(total_seconds / 86400.0))


def is_strictly_after(a_iso, b_iso):
    """True when instant a is strictly after instant b."""
    return parse_iso(a_iso) > parse_iso(b_iso)
