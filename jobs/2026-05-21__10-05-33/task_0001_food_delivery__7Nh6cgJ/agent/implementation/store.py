"""In-memory data store with a global lock for atomicity."""

from __future__ import annotations

import threading
from typing import Any


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.restaurants: dict[str, dict] = {}
        self.menu_items: dict[str, dict] = {}
        self.riders: dict[str, dict] = {}
        self.customers: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.assignments: dict[str, dict] = {}
        self.route_groups: dict[str, dict] = {}
        self.returns: dict[str, dict] = {}
        self.work_orders: dict[str, dict] = {}
        self.fines: dict[str, dict] = {}
        # uniqueness indexes
        self.restaurant_names: set[str] = set()  # active restaurant names
        self.customer_phones: set[str] = set()
        self.rider_phones: set[str] = set()

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
            self.work_orders.clear()
            self.fines.clear()
            self.restaurant_names.clear()
            self.customer_phones.clear()
            self.rider_phones.clear()


STORE = Store()
