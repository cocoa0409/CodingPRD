"""In-memory data store and logical clock for the closing/escrow API."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
class LogicalClock:
    """A monotonically advanceable clock used by the system.

    Tests drive the clock forward through /_clock/advance; otherwise the
    server boots with the wall-clock current time.
    """

    def __init__(self) -> None:
        self._now = datetime.now(timezone.utc).replace(microsecond=0)
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def set(self, new_now: datetime) -> datetime:
        if new_now.tzinfo is None:
            new_now = new_now.replace(tzinfo=timezone.utc)
        else:
            new_now = new_now.astimezone(timezone.utc)
        with self._lock:
            self._now = new_now
            return self._now


clock = LogicalClock()


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------
# Every entity is stored as a plain dict keyed by its UUID id.
parties: Dict[str, Dict[str, Any]] = {}
properties: Dict[str, Dict[str, Any]] = {}
escrow_files: Dict[str, Dict[str, Any]] = {}
earnest_money: Dict[str, Dict[str, Any]] = {}
title_searches: Dict[str, Dict[str, Any]] = {}
title_policies: Dict[str, Dict[str, Any]] = {}
ccr_disclosures: Dict[str, Dict[str, Any]] = {}
closing_disclosures: Dict[str, Dict[str, Any]] = {}
wire_instructions: Dict[str, Dict[str, Any]] = {}
disbursements: Dict[str, Dict[str, Any]] = {}
exchanges: Dict[str, Dict[str, Any]] = {}
audit_events: Dict[str, Dict[str, Any]] = {}

# Idempotency cache: key -> (request_body_hash, response_status_code, response_body_dict)
idempotency_cache: Dict[str, Any] = {}

# Tracks the operator who issued the latest ClosingDisclosure ISSUED transition
# per escrow_file_id. Used for the segregation-of-duties check on wire confirmation
# and disbursement approval.
cd_issuer_by_escrow_file: Dict[str, str] = {}


def reset_all() -> None:
    """Reset every in-memory table; used by the optional test reset endpoint."""
    parties.clear()
    properties.clear()
    escrow_files.clear()
    earnest_money.clear()
    title_searches.clear()
    title_policies.clear()
    ccr_disclosures.clear()
    closing_disclosures.clear()
    wire_instructions.clear()
    disbursements.clear()
    exchanges.clear()
    audit_events.clear()
    idempotency_cache.clear()
    cd_issuer_by_escrow_file.clear()
    clock.set(datetime.now(timezone.utc).replace(microsecond=0))


# A coarse global lock to serialize mutations. The benchmark explicitly tests
# concurrency semantics (first-writer-wins on status, OCC) and an in-process
# Python server with threaded=True needs explicit serialization to make those
# tests deterministic.
mutation_lock = threading.RLock()
