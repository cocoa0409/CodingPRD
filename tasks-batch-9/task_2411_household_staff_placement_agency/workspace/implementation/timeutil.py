"""Date / timestamp helpers.

PRD 2.4: created_at and updated_at are ISO 8601 UTC strings with exactly three
fractional digits.  PRD 2.11: a timestamp must be RFC 3339 UTC with a trailing
Z, a date must be YYYY-MM-DD and a month key must be YYYY-MM.
"""

import re
from datetime import date, datetime, timedelta, timezone

TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def format_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, dt.microsecond // 1000,
    )


def parse_timestamp(value):
    """Return an aware UTC datetime, or None when the value is not a valid
    RFC 3339 UTC timestamp with a trailing Z."""
    if not isinstance(value, str) or not TIMESTAMP_RE.match(value):
        return None
    body = value[:-1]
    if "." in body:
        head, frac = body.split(".", 1)
        frac = (frac + "000000")[:6]
    else:
        head, frac = body, "000000"
    try:
        base = datetime.strptime(head, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    return base.replace(microsecond=int(frac), tzinfo=timezone.utc)


def parse_date(value):
    """Return a date, or None when the value is not a valid YYYY-MM-DD date."""
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def parse_month(value):
    """Return (year, month) or None when the value is not a valid YYYY-MM key."""
    if not isinstance(value, str) or not MONTH_RE.match(value):
        return None
    year, month = int(value[0:4]), int(value[5:7])
    if month < 1 or month > 12:
        return None
    return year, month


def month_index(value):
    """Absolute month ordinal for a YYYY-MM key."""
    year, month = parse_month(value)
    return year * 12 + (month - 1)


def format_date(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def add_days(d, days):
    return d + timedelta(days=days)


def iso_week_key(dt):
    """PRD 3.4: the ISO year and week of start_at as YYYY-Www, weeks starting
    Monday 00:00:00.000Z."""
    iso = dt.astimezone(timezone.utc).isocalendar()
    return "%04d-W%02d" % (iso[0], iso[1])
