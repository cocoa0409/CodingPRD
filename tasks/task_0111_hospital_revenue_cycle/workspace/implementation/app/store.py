"""In-memory data store. Each entity has its own dict keyed by id."""
from __future__ import annotations

import threading
import uuid
from typing import Any

from .clock import CLOCK, format_iso


LOCK = threading.RLock()


class Store:
    def __init__(self) -> None:
        self.patients: dict[str, dict[str, Any]] = {}
        self.policies: dict[str, dict[str, Any]] = {}
        self.encounters: dict[str, dict[str, Any]] = {}
        self.charges: dict[str, dict[str, Any]] = {}
        self.coding_records: dict[str, dict[str, Any]] = {}
        # encounter_id -> coding_record_id (1:1 uniqueness)
        self.coding_by_encounter: dict[str, str] = {}
        self.clearance_decisions: dict[str, dict[str, Any]] = {}
        self.payments: dict[str, dict[str, Any]] = {}
        self.bad_debt_records: dict[str, dict[str, Any]] = {}
        # encounter_id -> bad_debt_record_id (1:1 uniqueness)
        self.bad_debt_by_encounter: dict[str, str] = {}
        # MRN uniqueness index
        self.mrn_to_patient: dict[str, str] = {}


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
    """id + created_at + updated_at + version=1."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def append_only_fields_create() -> dict[str, Any]:
    """id + created_at only for immutable audit records (ClearanceDecision, PatientPayment, BadDebtRecord)."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
    }


def bump_version(entity: dict[str, Any]) -> None:
    """Increment version and refresh updated_at on a mutable entity."""
    if "version" in entity:
        entity["version"] = int(entity.get("version", 0)) + 1
    entity["updated_at"] = now_iso()
