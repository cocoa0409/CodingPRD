"""In-memory data store with serialised access for first-writer-wins semantics."""
from __future__ import annotations

import threading
from typing import Any, Dict


class Store:
    def __init__(self) -> None:
        # Each table keyed by id -> dict
        self.parks: Dict[str, Dict[str, Any]] = {}
        self.visitors: Dict[str, Dict[str, Any]] = {}
        self.passes: Dict[str, Dict[str, Any]] = {}
        self.campgrounds: Dict[str, Dict[str, Any]] = {}
        self.lottery_permits: Dict[str, Dict[str, Any]] = {}
        self.backcountry_zones: Dict[str, Dict[str, Any]] = {}

        self.timed_entry_reservations: Dict[str, Dict[str, Any]] = {}
        self.campground_reservations: Dict[str, Dict[str, Any]] = {}
        self.lottery_applications: Dict[str, Dict[str, Any]] = {}
        self.backcountry_permits: Dict[str, Dict[str, Any]] = {}
        self.waitlist_entries: Dict[str, Dict[str, Any]] = {}
        self.ledger_entries: Dict[str, Dict[str, Any]] = {}

        # Uniqueness helpers
        self.park_names: Dict[str, str] = {}        # lower(name) -> park_id
        self.park_codes: Dict[str, str] = {}        # code -> park_id
        self.visitor_emails: Dict[str, str] = {}    # lower(email) -> visitor_id
        self.pass_serials: Dict[str, str] = {}      # serial -> pass_id

        # (park_id, lower(name)) -> resource_id for child-name uniqueness
        self.campground_names: Dict[tuple, str] = {}
        self.zone_names: Dict[tuple, str] = {}
        self.lottery_names: Dict[tuple, str] = {}

        # Coarse-grained lock for serialised mutation; in-memory operations
        # are quick enough that a single lock keeps semantics deterministic.
        self.lock = threading.RLock()


_STORE = Store()


def get_store() -> Store:
    return _STORE
