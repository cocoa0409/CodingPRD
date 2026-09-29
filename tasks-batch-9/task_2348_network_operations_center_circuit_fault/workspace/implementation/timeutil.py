"""Timestamp formatting / parsing and exact minute arithmetic."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

UTC = timezone.utc


def fmt(dt):
    """ISO 8601 UTC with milliseconds, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("z", "Z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def total_microseconds(delta):
    return delta.days * 86400 * 1000000 + delta.seconds * 1000000 + delta.microseconds


def minutes_between(start, end):
    """Exact elapsed minutes as a Decimal (may be negative)."""
    return Decimal(total_microseconds(end - start)) / Decimal(60000000)


def seconds_between(start, end):
    return Decimal(total_microseconds(end - start)) / Decimal(1000000)


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=float(minutes))


def truncate_seconds(dt):
    return dt.replace(microsecond=0)
