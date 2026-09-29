"""Logical clock and timestamp helpers (PRD §2.4)."""

import calendar
from datetime import datetime, timedelta, timezone

from db import db


def now():
    """Current logical clock instant (never wall time)."""
    return db.clock


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def real_now_str():
    return fmt(datetime.now(timezone.utc))


def parse_iso(value):
    """Parse an ISO 8601 instant; returns a tz-aware UTC datetime or None on failure."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_months(dt, months):
    """Advance by whole calendar months, clamping the day to the target month's last day."""
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)
