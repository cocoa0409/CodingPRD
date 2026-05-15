"""In-memory data store and common-field helpers."""
from __future__ import annotations

import threading
import uuid
from typing import Any

from .clock import CLOCK, format_iso


LOCK = threading.RLock()


class Store:
    def __init__(self) -> None:
        # Primary entity tables (id -> row)
        self.lots: dict[str, dict[str, Any]] = {}
        self.bidder_accounts: dict[str, dict[str, Any]] = {}
        self.auctions: dict[str, dict[str, Any]] = {}
        self.bids: dict[str, dict[str, Any]] = {}
        self.deposits: dict[str, dict[str, Any]] = {}
        self.confirmations: dict[str, dict[str, Any]] = {}
        self.payments: dict[str, dict[str, Any]] = {}
        self.transfer_orders: dict[str, dict[str, Any]] = {}
        self.audit_events: dict[str, dict[str, Any]] = {}

        # Inspection windows per lot — list of {start_at, end_at}
        self.inspection_windows: dict[str, list[dict[str, Any]]] = {}


_STORE = Store()


def get_store() -> Store:
    return _STORE


def reset_store() -> None:
    global _STORE
    _STORE = Store()
    CLOCK.reset()


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
