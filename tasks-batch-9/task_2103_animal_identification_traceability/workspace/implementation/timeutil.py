"""Temporal parsing / formatting (PRD 2.4).

Instants are aware UTC datetimes. Timestamps render as ISO 8601 UTC with three
fractional digits, e.g. 2026-08-01T00:00:00.000Z.
"""
import re
from datetime import date, datetime, timezone
from fractions import Fraction

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_instant(value):
    """Parse an ISO 8601 instant (date-only accepted as midnight UTC).
    Raises ValueError when malformed."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if not s:
        raise ValueError("empty")
    if DATE_RE.match(s):
        d = date.fromisoformat(s)
        return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    iso = s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s
    v = datetime.fromisoformat(iso)
    if v.tzinfo is None:
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value.strip()):
        raise ValueError("not a YYYY-MM-DD date")
    return date.fromisoformat(value.strip())


def fmt_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def day_start(d):
    return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)


def day_end(d):
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=timezone.utc)


def hours_between(later, earlier):
    """Exact elapsed hours as a Fraction: (later - earlier) seconds / 3600."""
    delta = later - earlier
    secs = Fraction(delta.days * 86400 + delta.seconds) + Fraction(delta.microseconds, 10 ** 6)
    return secs / 3600
