"""Temporal parsing/formatting helpers.

All server-assigned timestamps come from the logical clock (db.store.clock),
never from wall-clock time. Output timestamps are ISO 8601 UTC with three
fractional digits (PRD 2.4). Date-only fields (endorsement_expires_on) use
strict YYYY-MM-DD.
"""
import re
from datetime import date, datetime, timedelta, timezone

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def parse_datetime_value(v):
    """Parse an ISO 8601 datetime (a bare date is read as midnight UTC).
    Returns an aware UTC datetime. Raises ValueError on malformed input."""
    if isinstance(v, datetime):
        dt = v
    elif isinstance(v, str):
        s = v.strip()
        if DATE_RE.match(s):
            return datetime.combine(date.fromisoformat(s),
                                    datetime.min.time(), tzinfo=timezone.utc)
        iso = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError:
            raise ValueError("malformed datetime")
    else:
        raise ValueError("not a datetime value")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date_value(v):
    """Parse a strict YYYY-MM-DD date. Raises ValueError otherwise."""
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if not isinstance(v, str) or not DATE_RE.match(v.strip()):
        raise ValueError("not a YYYY-MM-DD date")
    try:
        return date.fromisoformat(v.strip())
    except ValueError:
        raise ValueError("not a valid calendar date")


def fmt_dt(dt):
    """aware datetime -> 'YYYY-MM-DDTHH:MM:SS.mmmZ' (PRD 2.4)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_opt_dt(dt):
    return None if dt is None else fmt_dt(dt)


def month_key(dt):
    """aware datetime -> (year, month) tuple for month comparisons."""
    return (dt.year, dt.month)


def parse_month(s):
    """'YYYY-MM' -> (year, month); raises ValueError when malformed."""
    if not isinstance(s, str) or not MONTH_RE.match(s.strip()):
        raise ValueError("not a YYYY-MM month")
    y, m = s.strip().split("-")
    return (int(y), int(m))


def month_window(year, month):
    """Half-open [first instant of month, first instant of next month)."""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)
