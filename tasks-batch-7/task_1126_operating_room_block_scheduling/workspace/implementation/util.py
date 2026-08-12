"""Time, precision, and interval helpers."""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import db

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def now_iso():
    """Logical-clock timestamp with three fractional digits (ISO 8601 UTC)."""
    dt = db.clock
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def iso_seconds(dt):
    """ISO8601 UTC rendered to the second, e.g. 2026-04-28T09:00:00Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_datetime(value):
    if not isinstance(value, str):
        raise ValueError("not a string")
    v = value
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD string to a datetime.date; raise ValueError otherwise."""
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise ValueError("bad date")
    return datetime.strptime(value, "%Y-%m-%d").date()


def compute_release_deadline(date_str, start_minute, release_deadline_hours):
    day = parse_date(date_str)
    midnight = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return midnight + timedelta(minutes=start_minute) - timedelta(hours=release_deadline_hours)


def prime_overlap(start, end, date_str):
    """Minutes of [start, end) inside the weekday prime window [420, 1020)."""
    d = parse_date(date_str)
    if d.weekday() >= 5:  # Saturday=5, Sunday=6
        return 0
    return max(0, min(end, 1020) - max(start, 420))


def round_half_up_int(value):
    """Round a Decimal to integer minutes, half up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_dec(value, places):
    q = Decimal(1).scaleb(-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))
