"""In-memory data store.

A single Store instance lives for the lifetime of the process. All resource
collections are held as dicts keyed by id. The store carries the logical
clock so timestamps are sourced from a single place.
"""
from __future__ import annotations

import threading

from .clock import LogicalClock


class Store:
    def __init__(self) -> None:
        self.clock = LogicalClock()
        self.lock = threading.RLock()

        # Top-level resources (with version + updated_at)
        self.restaurants: dict[str, dict] = {}
        self.menu_items: dict[str, dict] = {}
        self.riders: dict[str, dict] = {}
        self.customers: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.returns: dict[str, dict] = {}
        self.work_orders: dict[str, dict] = {}

        # Internal operational records (only id + created_at)
        self.assignments: dict[str, dict] = {}
        self.route_groups: dict[str, dict] = {}
        self.fines: dict[str, dict] = {}

    # --- helpers ---------------------------------------------------------

    def now_iso(self) -> str:
        return self.clock.now_iso()

    def find_customer_by_phone(self, phone: str) -> dict | None:
        for c in self.customers.values():
            if c["phone"] == phone:
                return c
        return None

    def find_rider_by_phone(self, phone: str) -> dict | None:
        for r in self.riders.values():
            if r["phone"] == phone:
                return r
        return None

    def find_restaurant_name_clash(self, name: str, *, exclude_id: str | None = None) -> bool:
        """A name clash is forbidden among *active* restaurants per PRD §3.1."""
        for r in self.restaurants.values():
            if exclude_id is not None and r["id"] == exclude_id:
                continue
            if r["name"] == name and r["status"] != "CLOSED":
                return True
        return False
