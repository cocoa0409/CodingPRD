"""In-memory data store for the Dog Walking & Pet Boarding API.

The store starts empty on every boot. NO seeding, NO preload, NO hardcoded
entities. Every entity must be created via the declared API surface.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any


# ---------- Stores ----------
# Each store keyed by entity id (UUID string).
owners: dict[str, dict[str, Any]] = {}
sitters: dict[str, dict[str, Any]] = {}
background_checks: dict[str, dict[str, Any]] = {}
pets: dict[str, dict[str, Any]] = {}
emergency_contacts: dict[str, dict[str, Any]] = {}
meet_and_greets: dict[str, dict[str, Any]] = {}
bookings: dict[str, dict[str, Any]] = {}
key_handoffs: dict[str, dict[str, Any]] = {}
gps_tracks: dict[str, dict[str, Any]] = {}
insurance_claims: dict[str, dict[str, Any]] = {}


# Logical system clock (overridable via POST /api/v1/_clock/set_current_utc).
# When None, fall back to wall clock UTC.
_logical_clock: dict[str, datetime | None] = {"now": None}

# Global lock for atomicity of multi-entity mutations.
lock = threading.RLock()


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    # Hex chars, prefixed "req_". 20 hex chars after the prefix.
    return "req_" + uuid.uuid4().hex[:20]


def utcnow() -> datetime:
    if _logical_clock["now"] is not None:
        return _logical_clock["now"]
    return datetime.now(timezone.utc)


def set_clock(dt: datetime) -> None:
    _logical_clock["now"] = dt


def fmt_ts(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # Microseconds → milliseconds; truncate to 3 fractional digits.
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def parse_ts(s: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into a tz-aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("timestamp must be a string")
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reset_all() -> None:
    """Reset all stores (used only by tests if they wish; not called at boot)."""
    with lock:
        for store in (
            owners,
            sitters,
            background_checks,
            pets,
            emergency_contacts,
            meet_and_greets,
            bookings,
            key_handoffs,
            gps_tracks,
            insurance_claims,
        ):
            store.clear()
        _logical_clock["now"] = None
