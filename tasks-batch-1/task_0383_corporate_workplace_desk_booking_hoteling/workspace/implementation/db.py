"""In-memory data store.

Stores start EMPTY on every boot. The test harness restarts this process
before every test, so there is no carry-over state. Tests build all
preconditions through the declared API surface. Nothing is seeded here.
"""
from __future__ import annotations

import uuid
import itertools
from datetime import datetime, timezone
from typing import Dict, Any


# ---- id / timestamp / request-id helpers ----------------------------------

def new_uuid() -> str:
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO 8601 UTC timestamp with exactly three fractional digits, suffix 'Z'.

    Used for created_at/updated_at (real wall time of the mutation). The
    *logical clock* (see `clock` below) is separate and only governs grace /
    no-show evaluation.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    """`req_` prefix + 20 alphanumeric chars (PRD §2.2)."""
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# Monotonic creation sequence — guarantees a stable ascending order even when
# many entities are created within the same millisecond (PRD §2.3 sorts list
# results by created_at ascending; ties resolved by creation order).
_seq = itertools.count(1)


def next_seq() -> int:
    return next(_seq)


# ---- stores (fresh empty dicts on every module load) ----------------------

sites: Dict[str, Dict[str, Any]] = {}
floors: Dict[str, Dict[str, Any]] = {}
neighborhoods: Dict[str, Dict[str, Any]] = {}
seats: Dict[str, Dict[str, Any]] = {}
rooms: Dict[str, Dict[str, Any]] = {}
employees: Dict[str, Dict[str, Any]] = {}
reservations: Dict[str, Dict[str, Any]] = {}
checkins: Dict[str, Dict[str, Any]] = {}
amenity_requests: Dict[str, Dict[str, Any]] = {}
no_show_events: Dict[str, Dict[str, Any]] = {}
capacity_policies: Dict[str, Dict[str, Any]] = {}
visitor_passes: Dict[str, Dict[str, Any]] = {}


# ---- logical clock (test-driving; PRD §2.7) -------------------------------
# Not an entity test precondition — system infrastructure. Holds the current
# local date and minute-of-day consulted by check-in grace and the no-show
# sweep. Starts unset; a FacilityManager sets it via POST /workplace/_clock/set.
clock: Dict[str, Any] = {
    "current_date": None,
    "current_minute": None,
}
