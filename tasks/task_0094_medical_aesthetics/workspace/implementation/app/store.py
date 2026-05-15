"""In-memory data store. Each entity has its own dict keyed by id."""
from __future__ import annotations

import threading
import uuid
from typing import Any

from .clock import CLOCK, format_iso


LOCK = threading.RLock()


class Store:
    def __init__(self) -> None:
        self.projects: dict[str, dict[str, Any]] = {}
        self.contraindication_rules: dict[str, dict[str, Any]] = {}
        self.consumable_skus: dict[str, dict[str, Any]] = {}
        self.rooms: dict[str, dict[str, Any]] = {}
        self.customers: dict[str, dict[str, Any]] = {}
        self.treatment_plans: dict[str, dict[str, Any]] = {}
        self.appointments: dict[str, dict[str, Any]] = {}
        self.operative_records: dict[str, dict[str, Any]] = {}
        # appointment_id -> operative_record_id (1:1)
        self.op_record_by_appointment: dict[str, str] = {}
        self.followups: dict[str, dict[str, Any]] = {}
        self.adverse_events: dict[str, dict[str, Any]] = {}
        self.installment_plans: dict[str, dict[str, Any]] = {}
        # treatment_plan_id -> installment_plan_id (1:1)
        self.installment_by_plan: dict[str, str] = {}
        self.payment_events: dict[str, dict[str, Any]] = {}
        self.audit_entries: dict[str, dict[str, Any]] = {}
        self.sync_events: dict[str, dict[str, Any]] = {}


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
