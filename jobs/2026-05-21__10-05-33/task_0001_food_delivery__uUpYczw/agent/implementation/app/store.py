"""In-memory data store.

Uses a single coarse-grained reentrant lock to serialize mutations across
all collections; this is enough for the deterministic single-process server
described in the PRD, and lets first-writer-wins races resolve naturally.
"""
from __future__ import annotations

import threading
from typing import Any


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()

        self.restaurants: dict[str, dict[str, Any]] = {}
        self.menu_items: dict[str, dict[str, Any]] = {}
        self.riders: dict[str, dict[str, Any]] = {}
        self.customers: dict[str, dict[str, Any]] = {}
        self.orders: dict[str, dict[str, Any]] = {}
        self.assignments: dict[str, dict[str, Any]] = {}
        self.route_groups: dict[str, dict[str, Any]] = {}
        self.returns: dict[str, dict[str, Any]] = {}
        self.fines: dict[str, dict[str, Any]] = {}
        self.work_orders: dict[str, dict[str, Any]] = {}

        # Unique-phone indexes ensure cross-record uniqueness invariants.
        self.customer_phones: set[str] = set()
        self.rider_phones: set[str] = set()


def get_store() -> Store:
    from flask import current_app

    return current_app.config["STORE"]


def get_clock():
    from flask import current_app

    return current_app.config["CLOCK"]
