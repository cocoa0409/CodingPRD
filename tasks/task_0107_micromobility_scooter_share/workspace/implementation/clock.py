"""Logical UTC clock (PRD §3.9).

A clock-setting capability (POST /api/_clock/set_current_utc) pins the server's
logical UTC clock to a supplied instant; every server-stamped timestamp
thereafter — trip started_at, segment clocks, trip ended_at, and report
windows — uses that value until it is changed again.

Until the clock is set, the server falls back to real wall-clock UTC. State is
process-local and wiped on every boot (start.sh re-invocation).
"""
from datetime import datetime, timezone

# When None, fall back to real wall-clock time. When set, every server-stamped
# timestamp reads exactly this instant.
_pinned = None


def set_clock(dt):
    """Pin the logical clock to an aware UTC datetime."""
    global _pinned
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _pinned = dt.astimezone(timezone.utc)


def now():
    """Current logical UTC instant as an aware datetime."""
    if _pinned is not None:
        return _pinned
    return datetime.now(timezone.utc)


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4)."""
    dt = now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
