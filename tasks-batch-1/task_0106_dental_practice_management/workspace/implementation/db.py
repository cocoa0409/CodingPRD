"""In-memory data store for the Dental Practice Management API.

All stores start EMPTY on every boot. The test harness restarts this process
(via start.sh) before every individual test, so there is no carry-over state.
Nothing is seeded, preloaded, or hardcoded here — every entity is created by the
tests through the declared API surface.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict


def new_uuid() -> str:
    """Server-minted id formatted as a UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4).

    Used for created_at / updated_at / api_request_timestamp — wall-clock time of
    a server-side event. This is distinct from the deterministic logical clock
    (see clock.py) which drives waiting/frequency/recare/expiry evaluation.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    """Server-generated request id starting with 'req_' (PRD §2.2)."""
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# ---------------------------------------------------------------------------
# Stores — one dict per entity, keyed by id. Cleared at module load each boot.
# ---------------------------------------------------------------------------
patients: Dict[str, Dict[str, Any]] = {}
providers: Dict[str, Dict[str, Any]] = {}
operatories: Dict[str, Dict[str, Any]] = {}
insurance_plans: Dict[str, Dict[str, Any]] = {}
patient_coverages: Dict[str, Dict[str, Any]] = {}
tooth_chart_entries: Dict[str, Dict[str, Any]] = {}
treatment_plans: Dict[str, Dict[str, Any]] = {}
treatment_plan_items: Dict[str, Dict[str, Any]] = {}
appointments: Dict[str, Dict[str, Any]] = {}
predeterminations: Dict[str, Dict[str, Any]] = {}
claims: Dict[str, Dict[str, Any]] = {}
claim_attachments: Dict[str, Dict[str, Any]] = {}
recare_recalls: Dict[str, Dict[str, Any]] = {}
payment_plans: Dict[str, Dict[str, Any]] = {}

# Monotonic sequence so list endpoints can sort by creation order deterministically
# even when two resources share a millisecond timestamp (PRD §2.3 ascending by
# creation). Each record stores a private "_seq".
_seq_counter = {"n": 0}


def next_seq() -> int:
    _seq_counter["n"] += 1
    return _seq_counter["n"]
