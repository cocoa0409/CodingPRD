"""In-memory data store with one big lock for sequential consistency.

Every entity collection is a plain dict keyed by id. A single
``threading.RLock`` serializes every mutation, satisfying the PRD §2.11
"immediately consistent" promise and the §3.13 concurrency-race
serialization rules.
"""
from __future__ import annotations

import threading
import uuid
from typing import Any, Dict


# Single global mutex protects every collection.
LOCK = threading.RLock()


# Each store is keyed by entity id (uuid) → dict
regions: Dict[str, Dict[str, Any]] = {}
geofences: Dict[str, Dict[str, Any]] = {}
bikes: Dict[str, Dict[str, Any]] = {}
riders: Dict[str, Dict[str, Any]] = {}
rides: Dict[str, Dict[str, Any]] = {}
work_orders: Dict[str, Dict[str, Any]] = {}
transfer_orders: Dict[str, Dict[str, Any]] = {}
loss_records: Dict[str, Dict[str, Any]] = {}
audit_logs: Dict[str, Dict[str, Any]] = {}

# Tracks every (region_id, bike_id) pair where bike was historically ON_SHELF.
# Used by region_loss_rate: bikes that were once on-shelf in this region
# count toward deployed_lifetime even after transfer out.
bike_region_history: Dict[str, set] = {}  # region_id -> set of bike_ids


def new_id() -> str:
    return str(uuid.uuid4())


def record_bike_in_region_history(region_id: str, bike_id: str) -> None:
    if not region_id:
        return
    bike_region_history.setdefault(region_id, set()).add(bike_id)
