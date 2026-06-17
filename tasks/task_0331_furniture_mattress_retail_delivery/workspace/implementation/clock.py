"""Server test clock (PRD §3.12).

A StoreManager may pin the server's notion of "now" via POST /_clock/set_current_utc.
Every system-stamped timestamp (created_at, filed_on, delivered_on baseline) reads
from here. State is module-global and resets to real time on every process boot,
which is exactly what per-test-server isolation requires.
"""
from datetime import datetime, timezone

# When None, use the real wall clock. Otherwise a fixed aware datetime (UTC).
_fixed_now = None


def set_now(dt):
    """Pin the clock to a timezone-aware UTC datetime."""
    global _fixed_now
    _fixed_now = dt


def now():
    """Current UTC instant — pinned value if set, else real wall clock."""
    if _fixed_now is not None:
        return _fixed_now
    return datetime.now(timezone.utc)


def iso_now():
    """ISO 8601 UTC string with exactly three fractional digits (PRD §2.4)."""
    return format_iso(now())


def format_iso(dt):
    """Format a datetime as ISO 8601 UTC with milliseconds, e.g. 2025-05-24T10:30:00.123Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 timestamp into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
