import threading
import uuid
from datetime import datetime, timezone


def _now_iso() -> str:
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.current_minute = 0
        self.operating_rooms = {}      # id -> dict
        self.surgical_cases = {}
        self.staff_members = {}
        self.case_assignments = {}
        self.instrument_sets = {}
        self.instrument_bookings = {}
        self.settlements = {}
        self.audit_entries = {}

        # creation order trackers (for created_at ordering when stamps collide)
        self._seq = 0

    def reset(self):
        with self.lock:
            self.current_minute = 0
            self.operating_rooms.clear()
            self.surgical_cases.clear()
            self.staff_members.clear()
            self.case_assignments.clear()
            self.instrument_sets.clear()
            self.instrument_bookings.clear()
            self.settlements.clear()
            self.audit_entries.clear()
            self._seq = 0

    def new_id(self) -> str:
        return str(uuid.uuid4())

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def stamp_create(self, entity: dict, with_version: bool = True):
        ts = _now_iso()
        entity["id"] = self.new_id()
        entity["created_at"] = ts
        if with_version:
            entity["updated_at"] = ts
            entity["version"] = 1
        entity["_seq"] = self.next_seq()

    def stamp_update(self, entity: dict):
        entity["updated_at"] = _now_iso()
        entity["version"] = entity.get("version", 1) + 1


db = DB()
