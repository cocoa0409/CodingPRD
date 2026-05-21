"""In-memory data store. Single-process, holds all entities by id."""
from __future__ import annotations

import threading
from typing import Any, Dict


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.restaurants: Dict[str, dict] = {}
        self.menu_items: Dict[str, dict] = {}
        self.riders: Dict[str, dict] = {}
        self.customers: Dict[str, dict] = {}
        self.orders: Dict[str, dict] = {}
        self.assignments: Dict[str, dict] = {}
        self.route_groups: Dict[str, dict] = {}
        self.returns: Dict[str, dict] = {}
        self.fines: Dict[str, dict] = {}
        self.work_orders: Dict[str, dict] = {}

    def reset(self) -> None:
        with self.lock:
            self.restaurants.clear()
            self.menu_items.clear()
            self.riders.clear()
            self.customers.clear()
            self.orders.clear()
            self.assignments.clear()
            self.route_groups.clear()
            self.returns.clear()
            self.fines.clear()
            self.work_orders.clear()


store = Store()
