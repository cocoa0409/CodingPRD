"""Logical clock, UUID minting, and ISO-8601 helpers (PRD §2.4, §2.10, §3.10).

The 'current clock' is the server's logical UTC instant, advanced only by
POST /_clock/set_current_utc. It starts at a fixed default epoch on each boot
(in-memory only; no persistence). System timestamps for created_at/updated_at,
prepped_at, logged_at use the wall clock per the standard envelope, while the
operability/permit/booking sweeps reason against the logical clock.
"""

import datetime
import uuid


def now_iso():
    """Wall-clock ISO 8601 UTC with three fractional digits (millis)."""
    dt = datetime.datetime.now(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def parse_iso(value):
    """Parse an ISO 8601 instant into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Returns None when the value
    is not a parseable instant.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)
