"""Timestamp parsing / formatting and whole-day arithmetic (PRD §2.4, §2.5)."""

import math
from datetime import datetime, timedelta, timezone

UTC = timezone.utc


def parse_iso(value):
    """Parse an ISO-8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_iso(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now():
    return datetime.now(UTC)


def whole_days(later, earlier):
    """floor((later - earlier) / 86400 seconds).  May be zero or negative."""
    return math.floor((later - earlier).total_seconds() / 86400.0)


def add_days(dt, days):
    return dt + timedelta(days=days)


def day_span(start, end):
    """Count of distinct UTC calendar dates the closed interval touches."""
    if start is None or end is None:
        return 0
    delta = (end.date() - start.date()).days + 1
    return delta if delta > 0 else 0


def intervals_intersect_closed(a_start, a_end, b_start, b_end):
    """Closed-interval intersection test (endpoints inclusive)."""
    return a_start <= b_end and b_start <= a_end
