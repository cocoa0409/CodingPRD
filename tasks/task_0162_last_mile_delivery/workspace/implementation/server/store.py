"""In-memory data store with per-resource maps and an atomic global lock."""
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from .clock import clock, iso8601_ms


# Coarse global lock. Adequate for benchmark correctness across cascade ops.
lock = threading.RLock()


# Entity tables. Each is a dict keyed by id (uuid str).
customers: Dict[str, dict] = {}
addresses: Dict[str, dict] = {}
transit_centers: Dict[str, dict] = {}
drivers: Dict[str, dict] = {}
parcels: Dict[str, dict] = {}
routes: Dict[str, dict] = {}
route_stops: Dict[str, dict] = {}
delivery_attempts: Dict[str, dict] = {}
appointments: Dict[str, dict] = {}


def new_id() -> str:
    return str(uuid.uuid4())


def now_str() -> str:
    return iso8601_ms(clock.now())


def stamp_create(entity: dict, with_version: bool = True) -> dict:
    ts = now_str()
    entity.setdefault("id", new_id())
    entity["created_at"] = ts
    if with_version:
        entity["updated_at"] = ts
        entity["version"] = 1
    return entity


def stamp_update(entity: dict) -> dict:
    if "version" in entity:
        entity["version"] += 1
    if "updated_at" in entity:
        entity["updated_at"] = now_str()
    elif "created_at" in entity and "version" not in entity:
        # Lightweight entity — still refresh created_at? No. Created is immutable. Skip.
        pass
    return entity


def stamp_lightweight_create(entity: dict) -> dict:
    entity.setdefault("id", new_id())
    entity["created_at"] = now_str()
    return entity
