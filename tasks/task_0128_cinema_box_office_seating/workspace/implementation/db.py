"""In-memory data store for the Cinema Box Office & Seating API.

Every store is a plain dict keyed by entity id. All stores start EMPTY on each
fresh boot — the test harness restarts this process (via start.sh) before every
test, so there is no carry-over state and nothing is ever seeded at startup.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict

import clock


def new_uuid() -> str:
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits (logical clock)."""
    return clock.now_iso()


def new_request_id() -> str:
    """`req_` prefix + 20 alphanumeric chars (PRD §2.2)."""
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# A monotonically increasing sequence used to give entities a stable,
# strictly-increasing creation order for the ascending-creation-time list sort
# (PRD §2.3). Logical-clock timestamps can collide / even move backwards.
_seq = 0


def next_seq() -> int:
    global _seq
    _seq += 1
    return _seq


# ---- stores (cleared at module load on each fresh boot) ---------------------

auditoriums: Dict[str, Dict[str, Any]] = {}
films: Dict[str, Dict[str, Any]] = {}
distributors: Dict[str, Dict[str, Any]] = {}
showtimes: Dict[str, Dict[str, Any]] = {}
seats: Dict[str, Dict[str, Any]] = {}
members: Dict[str, Dict[str, Any]] = {}
combos: Dict[str, Dict[str, Any]] = {}
orders: Dict[str, Dict[str, Any]] = {}
tickets: Dict[str, Dict[str, Any]] = {}
payments: Dict[str, Dict[str, Any]] = {}
settlements: Dict[str, Dict[str, Any]] = {}
