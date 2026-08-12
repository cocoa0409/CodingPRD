"""Temporal helpers.

Business timestamps come from the logical clock (db.store.clock) and are
formatted ISO 8601 UTC with three fractional digits (PRD 2.2/2.7).
Calendar-date fields (fill_date, accrual_date, effective_from/to) are plain
ISO dates (YYYY-MM-DD).
"""
import calendar
import re
from datetime import date, datetime, timedelta, timezone

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_datetime(value):
    """Parse an ISO-8601 datetime to an aware UTC datetime. Raises ValueError."""
    if isinstance(value, datetime):
        v = value
    elif isinstance(value, str):
        s = value.strip()
        if DATE_RE.match(s):
            # Lenient: a bare date denotes midnight UTC.
            d = date.fromisoformat(s)
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        iso = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
        try:
            v = datetime.fromisoformat(iso)
        except ValueError:
            raise ValueError("malformed datetime")
    else:
        raise ValueError("not a datetime value")
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO-8601 date (YYYY-MM-DD); datetime inputs yield their UTC date."""
    if isinstance(value, datetime):
        v = value
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError("not a date value")
    s = value.strip()
    if DATE_RE.match(s):
        return date.fromisoformat(s)
    return parse_datetime(s).date()


def fmt_dt(dt):
    """aware datetime -> 'YYYY-MM-DDTHH:MM:SS.mmmZ' (three fractional digits)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_date(d):
    if d is None:
        return None
    return d.isoformat()


def now_wall():
    """Wall-clock UTC for meta.api_request_timestamp (not the logical clock)."""
    return datetime.now(timezone.utc)


def days_in_month(d):
    return calendar.monthrange(d.year, d.month)[1]


def month_of(d):
    return (d.year, d.month)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)
