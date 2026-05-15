"""In-memory data store. Each entity has its own dict keyed by id."""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any


LOCK = threading.RLock()


# Monotonic timestamp generator — guarantees strictly-increasing created_at
# across rapid successive writes (so sort-by-created_at remains deterministic).
_TS_LOCK = threading.Lock()
_LAST_TS_US: int = 0


def _next_microseconds() -> int:
    global _LAST_TS_US
    with _TS_LOCK:
        now_us = int(time.time() * 1_000_000)
        if now_us <= _LAST_TS_US:
            now_us = _LAST_TS_US + 1
        _LAST_TS_US = now_us
        return now_us


def now_iso() -> str:
    """ISO 8601 UTC with three fractional digits (PRD §2.4)."""
    us = _next_microseconds()
    secs = us // 1_000_000
    micros = us % 1_000_000
    dt = datetime.fromtimestamp(secs, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{micros // 1000:03d}Z"


class Store:
    def __init__(self) -> None:
        # Configuration / master data
        self.warehouses: dict[str, dict[str, Any]] = {}
        self.zones: dict[str, dict[str, Any]] = {}
        self.bins: dict[str, dict[str, Any]] = {}
        self.suppliers: dict[str, dict[str, Any]] = {}
        self.products: dict[str, dict[str, Any]] = {}
        # Inbound
        self.receipts: dict[str, dict[str, Any]] = {}
        self.lots: dict[str, dict[str, Any]] = {}
        # Outbound
        self.shipments: dict[str, dict[str, Any]] = {}
        # Monitoring / deviations
        self.temperature_events: dict[str, dict[str, Any]] = {}
        self.deviations: dict[str, dict[str, Any]] = {}
        self.capas: dict[str, dict[str, Any]] = {}
        # Recall
        self.recalls: dict[str, dict[str, Any]] = {}
        self.recall_scope_entries: dict[str, dict[str, Any]] = {}
        # Per-recall list of recorded returns (each return references a
        # scope_entry_id and units), used by the preview-projection
        # endpoint to count distinct returned customers (PRD §3.7).
        self.recall_returns: dict[str, list[dict[str, Any]]] = {}
        # Audit / external sync
        self.external_events: dict[str, dict[str, Any]] = {}
        self.audit_entries: dict[str, dict[str, Any]] = {}

        # Per-warehouse certificate sequence counter.
        self.cert_seq: dict[str, int] = {}
        # Per-warehouse who-quarantined-receipt mapping (user_id of QAOfficer who quarantined).
        self.receipt_inspected_by: dict[str, str] = {}
        self.receipt_quarantined_by: dict[str, str] = {}
        # Per-deviation: actor_user_id who performed DEVIATION_ASSESS most recently.
        self.deviation_assessed_by: dict[str, str] = {}


_STORE = Store()


def get_store() -> Store:
    return _STORE


def reset_store() -> None:
    global _STORE
    _STORE = Store()


def new_id() -> str:
    return str(uuid.uuid4())


def common_fields_create() -> dict[str, Any]:
    """id + created_at + updated_at + version=1."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def common_fields_append_only() -> dict[str, Any]:
    """id + created_at only for append-only logs."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
    }


def bump_version(entity: dict[str, Any]) -> None:
    if "version" in entity:
        entity["version"] = int(entity.get("version", 0)) + 1
    entity["updated_at"] = now_iso()


def next_cert_seq(warehouse_id: str) -> int:
    store = get_store()
    cur = store.cert_seq.get(warehouse_id, 0) + 1
    store.cert_seq[warehouse_id] = cur
    return cur
