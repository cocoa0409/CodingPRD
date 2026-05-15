"""In-memory data store, UUID + timestamp helpers, and audit logging.

A single re-entrant lock guards mutations so multi-entity cascades stay
atomic relative to other requests.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from .clock import clock


def new_id() -> str:
    return str(uuid.uuid4())


def fmt_ts(dt: datetime) -> str:
    """ISO 8601 UTC, three fractional digits, Z suffix."""
    ms = f"{dt.microsecond // 1000:03d}"
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ms + "Z"


def now_ts() -> str:
    return fmt_ts(clock.now())


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        # Core domain collections
        self.core_enterprises: Dict[str, dict] = {}
        self.suppliers: Dict[str, dict] = {}
        self.payable_confirmations: Dict[str, dict] = {}
        self.receivables: Dict[str, dict] = {}
        self.financing_applications: Dict[str, dict] = {}
        self.disbursements: Dict[str, dict] = {}
        self.repayment_schedules: Dict[str, dict] = {}
        self.collection_cases: Dict[str, dict] = {}
        self.verifications: Dict[str, dict] = {}
        # Append-only logs
        self.audit_logs: List[dict] = []
        # Event sink (for ERP_SYNC / external emit events)
        self.events: List[dict] = []
        # Bookkeeping: latest confirmation per supplier (for tier-2+ parent resolution)
        # Implementation reads it via helpers; nothing else needed here.

    # ---- common stamps ----

    def stamp_create(self, payload: dict) -> dict:
        ts = now_ts()
        payload.setdefault("id", new_id())
        payload["created_at"] = ts
        payload["updated_at"] = ts
        payload["version"] = 1
        return payload

    def stamp_update(self, payload: dict) -> dict:
        payload["updated_at"] = now_ts()
        payload["version"] = int(payload.get("version", 0)) + 1
        return payload

    def stamp_event(self, payload: dict) -> dict:
        """For records that carry only `id` and `created_at`."""
        payload.setdefault("id", new_id())
        payload["created_at"] = now_ts()
        return payload

    # ---- audit log ----

    def append_audit(
        self,
        actor_role: str,
        actor_id: str,
        entity_type: str,
        entity_id: str,
        action: str,
        amount_cents: Optional[int] = None,
    ) -> dict:
        row = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "actor_role": actor_role,
            "actor_id": actor_id,
            "amount_cents": amount_cents,
            "occurred_at": now_ts(),
        }
        self.stamp_event(row)
        self.audit_logs.append(row)
        return row

    # ---- events (ERP_SYNC + admin emit) ----

    def emit_event(self, event_type: str, payload: dict) -> dict:
        row = {"event_type": event_type, "payload": payload}
        self.stamp_event(row)
        self.events.append(row)
        return row


store = Store()
