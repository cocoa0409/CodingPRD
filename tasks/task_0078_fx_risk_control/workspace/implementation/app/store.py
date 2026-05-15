"""In-memory data store and helpers.

All entities live in dictionaries keyed by id.  The store is intentionally
process-local — the benchmark only tests one server instance at a time.

A single re-entrant lock (`store.lock`) serialises every mutating request
end-to-end, which is what the §2.11 concurrency guarantees demand.  All
route handlers acquire it for the duration of their critical section.
"""
from __future__ import annotations

import threading
import uuid
from typing import Any, Optional

from app.clock import clock, format_iso


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return clock.now_iso()


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()

        self.traders: dict[str, dict] = {}
        self.currency_pairs: dict[str, dict] = {}
        self.pair_index_by_code: dict[str, str] = {}  # code -> id
        self.limits: dict[str, dict] = {}
        self.limit_adjustments: dict[str, dict] = {}
        self.trades: dict[str, dict] = {}
        self.positions: dict[str, dict] = {}
        # position_index: (trader_id, pair_code) -> position_id
        self.position_index: dict[tuple[str, str], str] = {}
        self.stop_loss_events: dict[str, dict] = {}
        self.counterparties: dict[str, dict] = {}
        self.settlement_instructions: dict[str, dict] = {}
        # idempotency: (counterparty_id, value_date, client_request_id) -> [instruction_id, ...]
        self.settlement_idempotency: dict[tuple[str, str, str], list[str]] = {}
        self.compliance_reports: dict[str, dict] = {}
        self.audit_log: dict[str, dict] = {}

    # -- common helpers ------------------------------------------------
    def stamp_common(self, *, create: bool = True) -> dict[str, Any]:
        ts = now_iso()
        if create:
            return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}
        return {"updated_at": ts}

    def touch(self, row: dict[str, Any]) -> None:
        """Bump version + updated_at on a row that already exists."""
        if "version" in row:
            row["version"] = row["version"] + 1
        row["updated_at"] = now_iso()

    def audit(
        self,
        *,
        event_type: str,
        actor_user_id: str,
        actor_role: str,
        subject_entity: str,
        subject_id: str,
        before_snapshot: Optional[dict] = None,
        after_snapshot: Optional[dict] = None,
    ) -> dict:
        row = {
            "id": new_id(),
            "created_at": now_iso(),
            "event_type": event_type,
            "actor_user_id": actor_user_id,
            "actor_role": actor_role,
            "subject_entity": subject_entity,
            "subject_id": subject_id,
            "before_snapshot": before_snapshot,
            "after_snapshot": after_snapshot,
        }
        self.audit_log[row["id"]] = row
        return row


# module-level singleton
store = Store()


__all__ = ["store", "Store", "new_id", "now_iso", "format_iso"]
