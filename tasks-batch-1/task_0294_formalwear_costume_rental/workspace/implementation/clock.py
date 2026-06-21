"""Logical system clock (PRD §3.10).

A StoreManager controls the clock for test-driving. The clock is the source of
truth for "the current moment" used in window-coherence checks, the overdue
sweep, and server-minted timestamps. ISO 8601 UTC with exactly 3 fractional
digits (PRD §2.4).

All state lives in module globals so a fresh process boot resets it.
"""
from datetime import datetime, timezone

# Monotone counter so that two entities created at the same logical instant
# still get strictly increasing created_at values for deterministic ordering.
# created_at is the documented tie-break / sweep-order key (PRD §2.4).
_clock_state = {
    "now": None,            # current logical instant (datetime, tz-aware UTC)
    "seq": 0,               # monotone sequence to disambiguate equal instants
}


def _default_now():
    return datetime.now(timezone.utc)


def set_clock(dt):
    _clock_state["now"] = dt


def current_dt():
    """Return the current logical clock as a tz-aware UTC datetime."""
    if _clock_state["now"] is None:
        return _default_now()
    return _clock_state["now"]


def now_iso():
    """Current logical clock formatted as ISO 8601 UTC, 3 fractional digits."""
    return to_iso(current_dt())


def next_seq():
    _clock_state["seq"] += 1
    return _clock_state["seq"]


def to_iso(dt):
    """Format a tz-aware datetime as ISO 8601 UTC with 3 fractional digits and 'Z'."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 timestamp into a tz-aware UTC datetime, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
