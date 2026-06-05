"""Logical UTC clock (PRD §3.6, §3.9, SCAFFOLD POST /_clock/advance).

The server keeps a logical "current UTC instant". `POST /_clock/advance` pins it
to a supplied ISO-8601 instant; the pinned value then drives every time-based
decision (hold expiry, showtime start/end comparisons) and every server-stamped
timestamp (created_at / updated_at). Until the clock is pinned, the server falls
back to real wall-clock UTC.

State is process-local and wiped on every boot (start.sh re-invocation), so each
per-test-server restart starts with an un-pinned clock.
"""
from __future__ import annotations

from datetime import datetime, timezone

# When None -> fall back to real wall-clock UTC. When set -> every logical
# "now" reads exactly this instant.
_pinned: datetime | None = None


def parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 instant into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset; naive inputs are treated as UTC.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def set_clock(dt: datetime) -> None:
    """Pin the logical clock to an aware UTC datetime."""
    global _pinned
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    _pinned = dt.astimezone(timezone.utc)


def now() -> datetime:
    """Current logical UTC instant as an aware datetime."""
    if _pinned is not None:
        return _pinned
    return datetime.now(timezone.utc)


def now_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits and 'Z' (PRD §2.4)."""
    dt = now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def reset() -> None:
    """Test/boot helper: un-pin the clock."""
    global _pinned
    _pinned = None
