"""In-memory data store. Each entity has its own dict keyed by id."""
from __future__ import annotations

import threading
import uuid
from typing import Any

from .clock import CLOCK, format_iso


# Single lock — request handlers run under this for atomic cascades.
LOCK = threading.RLock()


class Store:
    def __init__(self) -> None:
        # entity_name -> { id -> dict }
        self.cabinets: dict[str, dict[str, Any]] = {}
        self.compartments: dict[str, dict[str, Any]] = {}
        self.pricing_profiles: dict[str, dict[str, Any]] = {}
        self.rentals: dict[str, dict[str, Any]] = {}
        self.insurance_claims: dict[str, dict[str, Any]] = {}
        self.repair_tickets: dict[str, dict[str, Any]] = {}
        self.revenue_records: dict[str, dict[str, Any]] = {}
        self.audit_events: dict[str, dict[str, Any]] = {}

        # (size_class, rental_mode) -> profile id (for uniqueness check)
        self.pricing_uniq: dict[tuple[str, str], str] = {}
        # (cabinet_id, slot_number) -> compartment id (for uniqueness check)
        self.slot_uniq: dict[tuple[str, int], str] = {}


_STORE = Store()


def get_store() -> Store:
    return _STORE


def reset_store() -> None:
    global _STORE
    _STORE = Store()
    # Note: CLOCK is intentionally not reset here. Test infrastructure
    # explicitly drives the logical clock via /_clock/advance.


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return format_iso(CLOCK.now)  # type: ignore[return-value]


def common_fields_create() -> dict[str, Any]:
    """Returns id + created_at + updated_at + version=0 fields."""
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 0,
    }


def common_fields_append_only() -> dict[str, Any]:
    """Returns id + created_at only (for immutable rows)."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
    }


def bump_version(entity: dict[str, Any]) -> None:
    if "version" in entity:
        entity["version"] = int(entity.get("version", 0)) + 1
    entity["updated_at"] = now_iso()
