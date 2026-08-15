"""Logical clock per PRD §2.6. Default 2026-08-01T00:00:00Z; set via the
test-driving endpoint. Never falls back to wall-clock time.
"""

from datetime import datetime, timezone

from db import DB


def parse_iso(s):
    """Parse an ISO 8601 string (allowing trailing Z) to an aware UTC datetime."""
    if s is None:
        return None
    if isinstance(s, datetime):
        dt = s
    else:
        s2 = s
        if s2.endswith("Z"):
            s2 = s2[:-1] + "+00:00"
        dt = datetime.fromisoformat(s2)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_iso_ms(dt):
    """Format an aware datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def now():
    return parse_iso(DB.clock)


def now_iso_ms():
    return format_iso_ms(now())


def set_clock(iso_str):
    DB.clock = format_iso_ms(parse_iso(iso_str))
