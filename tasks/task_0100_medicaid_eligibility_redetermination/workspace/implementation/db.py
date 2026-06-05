"""In-memory data store.

Stores start EMPTY on every boot. No seeding, no preloaded entities.
Tests construct all required state via the declared API surface. The test
harness restarts this process before every test, so there is no carry-over.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, Any


def new_uuid() -> str:
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO-8601 UTC timestamp with exactly three fractional digits, suffix 'Z'."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    """`req_` prefix + 20 alphanumeric chars."""
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# ---- stores (re-created empty at module load on each fresh boot) -------------

# StateRule is keyed by its state_code (the path param is stateCode).
state_rules: Dict[str, Dict[str, Any]] = {}
# FplSchedule keyed by uuid id (year is a unique secondary index).
fpl_schedules: Dict[str, Dict[str, Any]] = {}
fpl_by_year: Dict[int, str] = {}

households: Dict[str, Dict[str, Any]] = {}
members: Dict[str, Dict[str, Any]] = {}
income_sources: Dict[str, Dict[str, Any]] = {}
assets: Dict[str, Dict[str, Any]] = {}
applications: Dict[str, Dict[str, Any]] = {}
determinations: Dict[str, Dict[str, Any]] = {}
enrollments: Dict[str, Dict[str, Any]] = {}
redeterminations: Dict[str, Dict[str, Any]] = {}
appeals: Dict[str, Dict[str, Any]] = {}

# Monotonic sequence to break created_at ties deterministically when sorting
# list results (multiple resources can share the same millisecond timestamp).
_seq_counter = {"n": 0}


def next_seq() -> int:
    _seq_counter["n"] += 1
    return _seq_counter["n"]
