"""In-memory data store + logical clock."""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class _DataStore:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.clock: datetime = datetime.now(tz=timezone.utc)

        self.grids: Dict[str, Dict[str, Any]] = {}
        self.drivers: Dict[str, Dict[str, Any]] = {}
        self.riders: Dict[str, Dict[str, Any]] = {}
        self.rush_hour_windows: Dict[str, Dict[str, Any]] = {}
        self.quest_bonuses: Dict[str, Dict[str, Any]] = {}
        self.airport_queue: Dict[str, Dict[str, Any]] = {}  # by airport row id
        self.rides: Dict[str, Dict[str, Any]] = {}
        self.disputes: Dict[str, Dict[str, Any]] = {}
        self.heatmap_snapshots: Dict[str, Dict[str, Any]] = {}

        # insertion order (for created_at-asc ordering)
        self.insertion_order: Dict[str, List[str]] = {
            "grids": [],
            "drivers": [],
            "riders": [],
            "rush_hour_windows": [],
            "quest_bonuses": [],
            "airport_queue": [],
            "rides": [],
            "disputes": [],
            "heatmap_snapshots": [],
        }

        # Index: grid code -> grid id (unique constraint)
        self.grid_code_index: Dict[str, str] = {}

    def now(self) -> datetime:
        return self.clock

    def set_now(self, dt: datetime) -> None:
        self.clock = dt

    def insert(self, collection: str, entity: Dict[str, Any]) -> None:
        store = getattr(self, collection)
        store[entity["id"]] = entity
        self.insertion_order[collection].append(entity["id"])

    def list_collection(self, collection: str) -> List[Dict[str, Any]]:
        store = getattr(self, collection)
        order = self.insertion_order[collection]
        return [store[i] for i in order if i in store]


_STORE: Optional[_DataStore] = None


def reset_store() -> None:
    global _STORE
    _STORE = _DataStore()


def store() -> _DataStore:
    global _STORE
    if _STORE is None:
        _STORE = _DataStore()
    return _STORE
