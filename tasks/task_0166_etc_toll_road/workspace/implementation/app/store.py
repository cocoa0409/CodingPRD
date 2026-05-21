"""In-memory data store for all entities."""
import uuid
from threading import RLock
from typing import Dict, List, Optional

from .clock import iso_now


class Store:
    def __init__(self) -> None:
        self.lock = RLock()
        self.accounts: Dict[str, dict] = {}
        self.vehicles: Dict[str, dict] = {}
        self.transponders: Dict[str, dict] = {}
        self.toll_events: Dict[str, dict] = {}
        self.reload_events: Dict[str, dict] = {}
        self.violations: Dict[str, dict] = {}
        self.fines: Dict[str, dict] = {}
        self.interop_policies: Dict[str, dict] = {}
        # Track per-minute auto-reload guard: (account_id, "YYYY-MM-DDTHH:MM") -> True
        self.autoreload_minute_guard: Dict[tuple, bool] = {}

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())

    # ------------------------------------------------------------------
    # Common-field helpers
    # ------------------------------------------------------------------
    def stamp_new(self, entity: dict) -> dict:
        now = iso_now()
        entity.setdefault("id", self.new_id())
        entity["created_at"] = now
        entity.setdefault("updated_at", now)
        entity.setdefault("version", 1)
        return entity

    def stamp_event(self, entity: dict) -> dict:
        """Stamp an event-style record (id + created_at only)."""
        entity.setdefault("id", self.new_id())
        entity["created_at"] = iso_now()
        return entity

    def bump(self, entity: dict) -> dict:
        """Update an entity's updated_at/version after mutation."""
        if "version" in entity:
            entity["version"] = int(entity["version"]) + 1
        if "updated_at" in entity or "created_at" in entity:
            entity["updated_at"] = iso_now()
        return entity

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------
    def vehicles_of(self, account_id: str) -> List[dict]:
        return [v for v in self.vehicles.values() if v["account_id"] == account_id]

    def transponders_of(self, account_id: str) -> List[dict]:
        return [t for t in self.transponders.values() if t["account_id"] == account_id]

    def reloads_of(self, account_id: str) -> List[dict]:
        return [r for r in self.reload_events.values() if r["account_id"] == account_id]

    def fines_for_account(self, account_id: str) -> List[dict]:
        out = []
        for f in self.fines.values():
            v = self.violations.get(f.get("violation_id"))
            if v and v.get("account_id") == account_id:
                out.append(f)
        return out

    def find_vehicle_by_plate(self, plate_number: str, plate_state: str) -> Optional[dict]:
        for v in self.vehicles.values():
            if v["plate_number"] == plate_number and v["plate_state"] == plate_state:
                return v
        return None

    def find_transponder_by_serial(self, serial: str) -> Optional[dict]:
        for t in self.transponders.values():
            if t["serial_number"] == serial:
                return t
        return None


store = Store()
