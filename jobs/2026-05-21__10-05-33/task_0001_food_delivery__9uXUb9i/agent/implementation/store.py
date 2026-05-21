"""In-memory data store and logical clock."""
from __future__ import annotations

import threading
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from typing import Any, Optional


_lock = threading.RLock()

# A logical clock offset (in seconds, can be fractional) applied to wall time.
_clock_offset_seconds: float = 0.0


def now() -> datetime:
    """Return current logical time (UTC). Driven by wall clock + an admin-controlled offset."""
    with _lock:
        return datetime.now(timezone.utc) + timedelta(seconds=_clock_offset_seconds)


def advance_clock(seconds: float) -> None:
    global _clock_offset_seconds
    with _lock:
        _clock_offset_seconds += float(seconds)


def reset_clock() -> None:
    """Test helper: reset offset."""
    global _clock_offset_seconds
    with _lock:
        _clock_offset_seconds = 0.0


def lock() -> threading.RLock:
    return _lock


def iso_z(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits and Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    micro = dt.microsecond
    millis = micro // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def gen_id() -> str:
    """Server-generated UUID, no type prefix."""
    return str(uuid.uuid4())


_REQ_ID_ALPHABET = string.ascii_uppercase + string.digits


def gen_request_id() -> str:
    """req_ prefix followed by 20 random uppercase/digit chars."""
    body = "".join(random.choices(_REQ_ID_ALPHABET, k=20))
    return f"req_{body}"


# ---- Collections ----------------------------------------------------------
# Each "table" is a dict keyed by id. We also keep a few secondary indices
# (e.g., per-restaurant menu items) only when they make hot paths simpler.

restaurants: dict[str, dict[str, Any]] = {}
menu_items: dict[str, dict[str, Any]] = {}
customers: dict[str, dict[str, Any]] = {}
riders: dict[str, dict[str, Any]] = {}
orders: dict[str, dict[str, Any]] = {}
assignments: dict[str, dict[str, Any]] = {}
route_groups: dict[str, dict[str, Any]] = {}
fines: dict[str, dict[str, Any]] = {}
returns_: dict[str, dict[str, Any]] = {}
work_orders: dict[str, dict[str, Any]] = {}

# Per-rider rolling history (lists of dicts) used to compute rolling metrics.
# Each delivery record: {"on_time": bool}
# Each offer record: {"accepted": bool}
# Each rating record: {"rating": float}
rider_history: dict[str, dict[str, list]] = {}


def reset_all() -> None:
    """Wipe all in-memory state. Used by self-tests."""
    with _lock:
        restaurants.clear()
        menu_items.clear()
        customers.clear()
        riders.clear()
        orders.clear()
        assignments.clear()
        route_groups.clear()
        fines.clear()
        returns_.clear()
        work_orders.clear()
        rider_history.clear()
        reset_clock()
