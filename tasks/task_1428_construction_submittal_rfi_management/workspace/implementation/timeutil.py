"""Temporal parsing/formatting helpers + business-day arithmetic.

Temporal inputs are kept as (kind, value) tuples:
  kind == "date"     -> value is datetime.date (fields declared YYYY-MM-DD)
  kind == "datetime" -> value is an aware UTC datetime (ISO 8601 instants)
Output timestamps are ISO 8601 UTC with three fractional digits (PRD 2.4).
"""
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
    kind, v = tv
    if kind == "datetime":
        return v
    return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)


def as_date(tv):
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


def fmt_date(d):
    return None if d is None else d.isoformat()


# ---------------------------------------------------------------------------
# Business-day arithmetic (PRD 2.6)
# ---------------------------------------------------------------------------

def is_business_day(d, holidays):
    """d is datetime.date; holidays is a set of datetime.date."""
    return d.weekday() < 5 and d not in holidays


def add_business_days(base, n, holidays):
    """Forward business-day pass: base is day 0 and not counted. Advance n business days."""
    d = base
    remaining = n
    while remaining > 0:
        d = d + timedelta(days=1)
        if is_business_day(d, holidays):
            remaining -= 1
    return d


def sub_business_days(base, n, holidays):
    """Backward business-day pass: base is not counted. Step back n business days."""
    d = base
    remaining = n
    while remaining > 0:
        d = d - timedelta(days=1)
        if is_business_day(d, holidays):
            remaining -= 1
    return d


def business_day_duration(opened, answered, holidays):
    """Count of business days d with opened < d <= answered (same-day answer => 0)."""
    if answered <= opened:
        return 0
    count = 0
    d = opened
    while d < answered:
        d = d + timedelta(days=1)
        if is_business_day(d, holidays):
            count += 1
    return count


def parse_holidays(arr):
    """Convert list of YYYY-MM-DD strings to a set of dates. Raises ValueError."""
    out = set()
    for v in arr:
        if not isinstance(v, str) or not DATE_RE.match(v):
            raise ValueError("holiday must be YYYY-MM-DD")
        out.add(date.fromisoformat(v))
    return out
