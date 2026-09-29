"""Logical UTC clock helpers (PRD 2.4).

The server never reads wall-clock time for any business rule; every temporal
rule reads the logical clock, which starts at the fixed default
2026-08-01T00:00:00Z.
"""
from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def parse_iso(value):
    """Parse an ISO-8601 instant; returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("z") or text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now_iso():
    return iso(datetime.now(timezone.utc))


def days(count):
    return timedelta(days=count)


def hours(count):
    return timedelta(hours=count)
