"""In-memory data store.

A single ``Store`` instance owns per-entity dicts plus the global RLock that
serialises mutating operations.  Each entity is a plain dict.
"""

from __future__ import annotations

import threading
import uuid
from typing import Dict

from .timeutil import iso_now


def new_id() -> str:
    return str(uuid.uuid4())


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()

        self.carriers: Dict[str, dict] = {}
        self.eld_devices: Dict[str, dict] = {}
        self.vehicles: Dict[str, dict] = {}
        self.drivers: Dict[str, dict] = {}
        self.duty_events: Dict[str, dict] = {}
        self.daily_logs: Dict[str, dict] = {}
        self.violations: Dict[str, dict] = {}
        self.adverse_exemptions: Dict[str, dict] = {}

    @staticmethod
    def stamp_create(entity: dict, *, versioned: bool = True) -> dict:
        now = iso_now()
        entity["id"] = entity.get("id") or new_id()
        entity["created_at"] = now
        if versioned:
            entity["updated_at"] = now
            entity["version"] = 1
        return entity

    @staticmethod
    def bump(entity: dict) -> None:
        """Refresh updated_at + increment version on a versioned entity."""
        entity["updated_at"] = iso_now()
        entity["version"] = int(entity.get("version", 1)) + 1


store = Store()
