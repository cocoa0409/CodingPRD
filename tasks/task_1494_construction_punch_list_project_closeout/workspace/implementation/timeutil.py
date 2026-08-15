"""Temporal parsing/formatting helpers.

System timestamps (created_at, updated_at, api_request_timestamp) are ISO 8601
UTC with three fractional digits (PRD 2.2/2.5). Business datetime fields
(scheduled windows, SC date, SLA due, etc.) are emitted at second precision
(PRD 3.7: SLA timestamps are ISO 8601 UTC at second precision).
"""
from datetime import datetime, timedelta, timezone


def parse_dt(value):
    """Parse an ISO-8601 datetime to an aware UTC datetime. Raises ValueError
    on malformed input. Naive inputs are read as UTC."""
    if isinstance(value, datetime):
        v = value
    elif isinstance(value, str):
        s = value.strip()
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


def fmt_dt(dt):
    """aware datetime -> 'YYYY-MM-DDTHH:MM:SS.mmmZ' (PRD 2.5 system timestamps)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_sec(dt):
    """aware datetime -> 'YYYY-MM-DDTHH:MM:SSZ' (second-precision business fields)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_opt_sec(dt):
    return None if dt is None else fmt_sec(dt)


def add_business_days(dt, days):
    """Advance `days` business days from dt, skipping Saturdays and Sundays.
    dt is t0 and the first day counted is the next business day; the time of
    day is preserved (PRD 3.7 warranty_sla_due_at BUSINESS variant)."""
    cur = dt
    remaining = days
    while remaining > 0:
        cur = cur + timedelta(days=1)
        if cur.weekday() < 5:  # Monday..Friday
            remaining -= 1
    return cur
