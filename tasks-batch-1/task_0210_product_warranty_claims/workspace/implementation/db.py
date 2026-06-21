"""In-memory data store.

Stores start empty on every boot. The test harness restarts this process
before every test, so there is no carry-over state. Nothing is seeded here —
every entity is created by tests via the declared API surface.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict


def new_uuid() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    """ISO-8601 UTC timestamp with three fractional digits, suffix 'Z'.

    Used for created_at / updated_at (wall-clock server mutation time). The
    logical/test clock (system_clock["current_utc"]) is distinct and is what
    business temporal rules compare against.
    """
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id() -> str:
    raw = uuid.uuid4().hex + uuid.uuid4().hex
    return "req_" + raw[:20]


# ---- entity stores (cleared at module load each fresh boot) -----------------

products: Dict[str, Dict[str, Any]] = {}
owners: Dict[str, Dict[str, Any]] = {}
coverage_tiers: Dict[str, Dict[str, Any]] = {}
registrations: Dict[str, Dict[str, Any]] = {}
extended_warranties: Dict[str, Dict[str, Any]] = {}
proofs: Dict[str, Dict[str, Any]] = {}
claims: Dict[str, Dict[str, Any]] = {}
warranty_transfers: Dict[str, Dict[str, Any]] = {}
ledger_entries: Dict[str, Dict[str, Any]] = {}

# Monotonic insertion counter so created_at ordering is stable even when two
# rows are minted in the same millisecond (ISO timestamps only carry ms).
_seq_counter = {"n": 0}


def next_seq() -> int:
    _seq_counter["n"] += 1
    return _seq_counter["n"]


# Logical clock singleton (system infrastructure, not a business entity).
# Tests drive it via /_clock/set_current_utc and /_clock/advance. Defaults to
# epoch so that, absent a test setting it, temporal rules are deterministic.
system_clock: Dict[str, Any] = {
    "current_utc": "1970-01-01T00:00:00.000Z",
}
