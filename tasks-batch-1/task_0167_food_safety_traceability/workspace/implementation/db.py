"""In-memory data store for the Food Safety & Traceability API.

All stores start empty on every boot. The test harness restarts this process
before every test (per-test-server isolation), so there is no carry-over state.
No entity is ever seeded, preloaded, or hardcoded at startup.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, Any


def new_uuid() -> str:
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    """Server-generated request id starting with 'req_' (PRD §2.2)."""
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# A monotonically increasing counter to order resources created within the same
# millisecond. created_at timestamps may collide at ms precision, so every
# "ASC by created_at" rule that the PRD mandates is implemented as
# (created_at, _seq) to keep ordering deterministic.
_seq_counter = {"n": 0}


def next_seq() -> int:
    _seq_counter["n"] += 1
    return _seq_counter["n"]


# ---- stores (cleared at module load each fresh boot) ------------------------

facilities: Dict[str, Dict[str, Any]] = {}
suppliers: Dict[str, Dict[str, Any]] = {}
ingredients: Dict[str, Dict[str, Any]] = {}
allergen_profiles: Dict[str, Dict[str, Any]] = {}
lots: Dict[str, Dict[str, Any]] = {}
coas: Dict[str, Dict[str, Any]] = {}
production_runs: Dict[str, Dict[str, Any]] = {}
consumed_lots: Dict[str, Dict[str, Any]] = {}
ccp_readings: Dict[str, Dict[str, Any]] = {}
hold_orders: Dict[str, Dict[str, Any]] = {}
zones: Dict[str, Dict[str, Any]] = {}
bookings: Dict[str, Dict[str, Any]] = {}
