"""In-memory data store.

Storage is in-memory only — plain dicts keyed by id. Stores start empty on
every boot (the test harness restarts the process before every test), and no
entity is ever seeded, preloaded, or hardcoded. Every entity is created by a
test via the declared API surface.
"""
from __future__ import annotations

import uuid
import random
import string
from datetime import datetime, timezone
from typing import Dict, Any


def new_uuid() -> str:
    """A bare UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """Wall-clock ISO-8601 UTC timestamp with three fractional digits, 'Z'
    suffix (PRD §2.4 — created_at/updated_at are server wall-clock values)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    """`req_` prefix + 20 alphanumeric chars (PRD §2.2)."""
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


# ---- entity stores (cleared at module load each fresh boot) -----------------
clients: Dict[str, Dict[str, Any]] = {}
photographers: Dict[str, Dict[str, Any]] = {}
session_packages: Dict[str, Dict[str, Any]] = {}
bookings: Dict[str, Dict[str, Any]] = {}
payments: Dict[str, Dict[str, Any]] = {}
contracts: Dict[str, Dict[str, Any]] = {}
shoot_schedules: Dict[str, Dict[str, Any]] = {}
second_shooter_assignments: Dict[str, Dict[str, Any]] = {}
galleries: Dict[str, Dict[str, Any]] = {}
proof_selections: Dict[str, Dict[str, Any]] = {}
addon_orders: Dict[str, Dict[str, Any]] = {}
license_grants: Dict[str, Dict[str, Any]] = {}

# Monotonic insertion counter — list ordering ties broken by insertion order
# so created_at ascending is stable even within the same millisecond.
_seq = {"n": 0}


def next_seq() -> int:
    _seq["n"] += 1
    return _seq["n"]


# ---- logical clock (PRD §3.8) -----------------------------------------------
# StudioAdmin drives this via POST /studio/_clock/set_current_utc; shoot
# completion and cancellation lead-time read it. Defaults to epoch until set.
_clock = {"current_utc": "1970-01-01T00:00:00.000Z"}


def get_clock_iso() -> str:
    return _clock["current_utc"]


def set_clock_iso(value: str) -> None:
    _clock["current_utc"] = value
