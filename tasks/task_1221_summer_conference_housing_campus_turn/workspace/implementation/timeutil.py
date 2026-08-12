"""Temporal parsing/formatting helpers.

Temporal inputs are kept as (kind, value) tuples:
  kind == "date"     -> value is datetime.date (fields declared YYYY-MM-DD)
  kind == "datetime" -> value is an aware UTC datetime (ISO 8601 instants)
Output timestamps are ISO 8601 UTC with three fractional digits (PRD 2.4).
"""
import calendar
import re
from datetime import date, datetime, timedelta, timezone

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_temporal(value):
    """Parse an ISO-8601 date or datetime. Returns (kind, value).
    Raises ValueError on malformed input."""
    if isinstance(value, datetime):
        v = value
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return ("datetime", v.astimezone(timezone.utc))
    if isinstance(value, date):
        return ("date", value)
    if not isinstance(value, str):
        raise ValueError("not a temporal value")
    s = value.strip()
    if DATE_RE.match(s):
        return ("date", date.fromisoformat(s))
    iso = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
    try:
        v = datetime.fromisoformat(iso)
    except ValueError:
        raise ValueError("malformed datetime")
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return ("datetime", v.astimezone(timezone.utc))


def as_instant(tv):
    """(kind, value) -> aware UTC datetime (midnight UTC for dates)."""
    kind, v = tv
    if kind == "datetime":
        return v
    return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)


def as_date(tv):
    """(kind, value) -> datetime.date."""
    kind, v = tv
    if kind == "date":
        return v
    return v.date()


def fmt_dt(dt):
    """aware datetime -> 'YYYY-MM-DDTHH:MM:SS.mmmZ' (PRD 2.4 timestamp format)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_temporal(tv):
    if tv is None:
        return None
    kind, v = tv
    if kind == "date":
        return v.isoformat()
    return fmt_dt(v)


def fmt_opt_dt(dt):
    return None if dt is None else fmt_dt(dt)


def add_months(d, months):
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def add_years(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29 -> Feb 28
        return d.replace(year=d.year + years, day=28)


def nights_between(start_date, end_date):
    """Calendar dates d with start_date <= d < end_date."""
    out = []
    d = start_date
    while d < end_date:
        out.append(d)
        d += timedelta(days=1)
    return out
