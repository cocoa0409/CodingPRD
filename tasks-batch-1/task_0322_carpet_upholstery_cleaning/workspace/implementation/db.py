"""In-memory data store.

Storage is in-memory only (Python dicts keyed by id). Stores start EMPTY on
every boot — the test harness restarts this process before every test, so there
is never any carry-over state and nothing is ever seeded or preloaded.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict


def new_uuid() -> str:
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD §2.4)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    """Server-generated request id starting with 'req_' (PRD §2.2)."""
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# ---------------------------------------------------------------------------
# In-memory stores — one dict per entity, keyed by id. Cleared (recreated
# empty) on each fresh process boot at module import. NEVER seeded.
# ---------------------------------------------------------------------------
customers: Dict[str, Dict[str, Any]] = {}
service_catalogs: Dict[str, Dict[str, Any]] = {}
crews: Dict[str, Dict[str, Any]] = {}
recurring_plans: Dict[str, Dict[str, Any]] = {}
cleaning_jobs: Dict[str, Dict[str, Any]] = {}
room_assessments: Dict[str, Dict[str, Any]] = {}
add_ons: Dict[str, Dict[str, Any]] = {}
scheduled_slots: Dict[str, Dict[str, Any]] = {}
invoices: Dict[str, Dict[str, Any]] = {}
payments: Dict[str, Dict[str, Any]] = {}
guarantee_claims: Dict[str, Dict[str, Any]] = {}
wallet_ledger_entries: Dict[str, Dict[str, Any]] = {}

# Monotonic sequence used purely to define a stable created_at ASC ordering
# even when two rows share the same millisecond wall-clock timestamp. This is
# an internal tiebreaker (PRD: "tie-break created_at ASC, then it is already
# unique"); it is NOT an entity field exposed in any response payload.
_seq_counter = 0


def next_seq() -> int:
    global _seq_counter
    _seq_counter += 1
    return _seq_counter
