"""In-memory data store and logical clock. Fresh (empty) on every process boot."""
from datetime import datetime

from helpers import new_uuid, wall_now

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0)


class Store:
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        self.courses = {}
        self.time_slots = {}
        self.guides = {}
        self.participants = {}
        self.season_passes = {}
        self.groups = {}
        self.bookings = {}
        self.guide_assignments = {}
        self.gear_items = {}
        self.gear_checkouts = {}
        self.incident_reports = {}

    # -- sequence for stable creation ordering --
    def next_seq(self):
        self._seq += 1
        return self._seq

    # -- record scaffolding --
    def new_record(self, versioned=True):
        now = wall_now()
        rec = {
            "id": new_uuid(),
            "created_at": now,
            "_seq": self.next_seq(),
        }
        if versioned:
            rec["updated_at"] = now
            rec["version"] = 1
        return rec

    def touch(self, rec):
        rec["updated_at"] = wall_now()
        rec["version"] = rec.get("version", 1) + 1


store = Store()
