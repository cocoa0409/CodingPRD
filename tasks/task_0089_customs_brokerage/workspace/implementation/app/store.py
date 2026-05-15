"""In-memory data store. Each entity has its own dict keyed by id."""
from __future__ import annotations

import threading
import uuid
from typing import Any

from .clock import CLOCK, format_iso


LOCK = threading.RLock()


class Store:
    def __init__(self) -> None:
        self.clients: dict[str, dict[str, Any]] = {}
        self.agreements: dict[str, dict[str, Any]] = {}
        self.declarations: dict[str, dict[str, Any]] = {}
        self.documents: dict[str, dict[str, Any]] = {}
        self.filings: dict[str, dict[str, Any]] = {}
        self.inspection_cases: dict[str, dict[str, Any]] = {}
        self.settlements: dict[str, dict[str, Any]] = {}
        self.rejection_records: dict[str, dict[str, Any]] = {}
        self.audit_log: dict[str, dict[str, Any]] = {}
        self.external_events: dict[str, dict[str, Any]] = {}

        # PRE_VALIDATED actor (X-User-ID) per Declaration id — for SoD checks
        self.preval_actor: dict[str, str] = {}
        # File actor (X-User-ID) per Declaration id — for SoD on advance
        self.file_actor: dict[str, str] = {}


_STORE = Store()


def get_store() -> Store:
    return _STORE


def reset_store() -> None:
    global _STORE
    _STORE = Store()


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return format_iso(CLOCK.now)  # type: ignore[return-value]


def common_fields_create() -> dict[str, Any]:
    """id + created_at + updated_at + version=1 (per PRD §2.4: starts at 1)."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def common_fields_append_only() -> dict[str, Any]:
    """id + created_at only (for immutable rows like RejectionRecord, AuditLog)."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
    }


def bump_version(entity: dict[str, Any]) -> None:
    if "version" in entity:
        entity["version"] = int(entity.get("version", 0)) + 1
    entity["updated_at"] = now_iso()
