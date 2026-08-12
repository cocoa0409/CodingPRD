"""Temporal parsing/formatting helpers.

Resource timestamps are ISO 8601 UTC with three fractional digits (PRD 2.5),
e.g. 2025-05-24T10:30:00.123Z. Date-only fields (harvest window bounds,
work_date) stay 'YYYY-MM-DD'.
"""
import re
from datetime import date, datetime, timezone

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_datetime(value):
    """Parse an ISO-8601 datetime string to an aware UTC datetime.
    Raises ValueError on malformed input."""
    if not isinstance(value, str):
        raise ValueError("not a datetime string")
    s = value.strip()
    iso = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
    try:
        v = datetime.fromisoformat(iso)
    except ValueError:
        raise ValueError("malformed datetime")
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)


def parse_date(value):
    """Parse a 'YYYY-MM-DD' date string. Raises ValueError on malformed input."""
    if not isinstance(value, str) or not DATE_RE.match(value.strip()):
        raise ValueError("not a date string")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise ValueError("malformed date")


def date_as_instant(d):
    """A calendar date read as midnight UTC (00:00:00Z)."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def fmt_dt(dt):
    """aware datetime -> 'YYYY-MM-DDTHH:MM:SS.mmmZ' (PRD 2.5 timestamp format)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_dt_seconds(dt):
    """aware datetime -> 'YYYY-MM-DDTHH:MM:SSZ' (whole-second form used for the
    computed tag expiry instant)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_opt_dt(dt):
    return None if dt is None else fmt_dt(dt)
