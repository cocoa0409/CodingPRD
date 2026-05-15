"""In-memory data store."""
from __future__ import annotations

import threading
import uuid
from typing import Any

from .clock import CLOCK, format_iso


LOCK = threading.RLock()


class Store:
    def __init__(self) -> None:
        self.institutions: dict[str, dict[str, Any]] = {}
        self.regions: dict[str, dict[str, Any]] = {}
        self.persons: dict[str, dict[str, Any]] = {}
        self.facilities: dict[str, dict[str, Any]] = {}
        self.cases: dict[str, dict[str, Any]] = {}
        self.contact_events: dict[str, dict[str, Any]] = {}
        self.tracing_tasks: dict[str, dict[str, Any]] = {}
        self.isolations: dict[str, dict[str, Any]] = {}
        self.daily_reports: dict[str, dict[str, Any]] = {}
        self.test_orders: dict[str, dict[str, Any]] = {}
        self.risk_decisions: dict[str, dict[str, Any]] = {}
        self.supply_items: dict[str, dict[str, Any]] = {}
        self.supply_requests: dict[str, dict[str, Any]] = {}
        self.dispatches: dict[str, dict[str, Any]] = {}
        self.bulletins: dict[str, dict[str, Any]] = {}
        self.audit_logs: dict[str, dict[str, Any]] = {}

        # Auxiliary index: tracing_task_id -> list[contact_event_id]
        # tracking events linked to the tracing task (so we can identify
        # CLOSE-tier events to auto-create isolations for, and cancel
        # auto-created isolations on rejection).
        self.task_to_events: dict[str, list[str]] = {}
        # isolation_id -> tracing_task_id (auto-created isolations from a task)
        self.isolation_auto_task: dict[str, str] = {}


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
    """id + created_at only (no version, no updated_at)."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
    }


def bump_version(entity: dict[str, Any]) -> None:
    if "version" in entity:
        entity["version"] = int(entity.get("version", 0)) + 1
    entity["updated_at"] = now_iso()
