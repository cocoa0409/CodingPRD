"""Logical clock per PRD §2.11.

Default startup reading is exactly 2026-08-01T00:00:00Z; the clock never
falls back to wall-clock time. All server-side timestamps (created_at,
updated_at, fixed_at, approved_at, packed_at, roast_completed_at,
position_as_of, meta.api_request_timestamp) read from this clock and are
emitted as ISO 8601 UTC at second precision with a Z suffix.
"""

from datetime import datetime, timezone

from db import DB


def parse_iso(s):
    """Parse an ISO 8601 string (allowing trailing Z / offsets) to an aware UTC datetime."""
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


def fmt_iso(dt):
    """Format an aware datetime as ISO 8601 UTC at second precision with Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def now():
    """Current logical clock as an aware datetime."""
    return parse_iso(DB.clock)


def now_iso():
    return fmt_iso(now())


def set_clock(iso_str):
    DB.clock = fmt_iso(parse_iso(iso_str))
