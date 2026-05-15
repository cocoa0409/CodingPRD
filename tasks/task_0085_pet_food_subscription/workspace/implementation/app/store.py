"""In-memory data store for all entities."""
from __future__ import annotations

import threading
from typing import Any, Dict, List


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.customers: Dict[str, Dict[str, Any]] = {}
        self.pets: Dict[str, Dict[str, Any]] = {}
        self.subscriptions: Dict[str, Dict[str, Any]] = {}
        self.recipes: Dict[str, Dict[str, Any]] = {}
        self.recommendations: Dict[str, Dict[str, Any]] = {}
        self.warehouses: Dict[str, Dict[str, Any]] = {}
        self.inventory_lots: Dict[str, Dict[str, Any]] = {}
        self.orders: Dict[str, Dict[str, Any]] = {}
        self.feedbacks: Dict[str, Dict[str, Any]] = {}
        self.adjustments: Dict[str, Dict[str, Any]] = {}
        self.audit_logs: List[Dict[str, Any]] = []
        # Per-subscription pause history: list of {"from": iso, "to": iso}
        self.pause_windows: Dict[str, List[Dict[str, str]]] = {}
        # Warehouse daily capacity ledger: {warehouse_id: {date_key: int}}
        self.warehouse_daily_used: Dict[str, Dict[str, int]] = {}


store = Store()


def reset_store() -> None:
    """Test helper: wipe all in-memory state in place so callers
    holding the module-level `store` reference see the reset."""
    with store.lock:
        store.customers.clear()
        store.pets.clear()
        store.subscriptions.clear()
        store.recipes.clear()
        store.recommendations.clear()
        store.warehouses.clear()
        store.inventory_lots.clear()
        store.orders.clear()
        store.feedbacks.clear()
        store.adjustments.clear()
        store.audit_logs.clear()
        store.pause_windows.clear()
        store.warehouse_daily_used.clear()
