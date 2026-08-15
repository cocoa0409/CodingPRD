"""Temporal parsing/formatting helpers.

All domain timestamps in this task are ISO 8601 instants (scaffold type
"datetime"). Output timestamps are ISO 8601 UTC with three fractional digits
(PRD 2.2/2.5). period_month values are "YYYY-MM" strings.
"""
import calendar
import re
from datetime import datetime, timedelta, timezone

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def parse_instant(value):
    """Parse an ISO-8601 datetime (a trailing Z is accepted). A bare
    YYYY-MM-DD date is coerced to midnight UTC. Raises ValueError."""
    if isinstance(value, datetime):
        v = value
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)
    if not isinstance(value, str) or isinstance(value, bool):
        raise ValueError("not a datetime value")
    s = value.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    iso = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
    try:
        v = datetime.fromisoformat(iso)
    except ValueError:
        raise ValueError("malformed datetime")
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)


def fmt_dt(dt):
    """aware datetime -> 'YYYY-MM-DDTHH:MM:SS.mmmZ' (PRD 2.2 timestamp format)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_months(dt, months):
    """Whole-month arithmetic anchored to the source timestamp's day
    (day clamped to the target month's length)."""
    m = dt.month - 1 + months
    y = dt.year + m // 12
    m = m % 12 + 1
    day = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=day)


def parse_period(value):
    """Validate a YYYY-MM period string; returns (year, month). Raises ValueError."""
    if not isinstance(value, str) or not MONTH_RE.match(value):
        raise ValueError("bad period_month")
    return int(value[:4]), int(value[5:7])


def next_month(y, m):
    return (y + 1, 1) if m == 12 else (y, m + 1)


def period_due_ts(y, m):
    """23:59:59.999Z on the 10th day of the month following the period."""
    ny, nm = next_month(y, m)
    return datetime(ny, nm, 10, 23, 59, 59, 999000, tzinfo=timezone.utc)


def close_earliest_ts(y, m):
    """00:00:00Z on the 11th day of the month following the period."""
    ny, nm = next_month(y, m)
    return datetime(ny, nm, 11, 0, 0, 0, tzinfo=timezone.utc)


def current_period(dt):
    return "%04d-%02d" % (dt.year, dt.month)


def hours(n):
    return timedelta(hours=n)


def days(n):
    return timedelta(days=n)
