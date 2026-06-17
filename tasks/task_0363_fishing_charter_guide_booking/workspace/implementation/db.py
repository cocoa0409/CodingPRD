"""In-memory data store. Starts empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone

from response import now_iso


class Store:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.marinas = {}
        self.dock_slots = {}
        self.boats = {}
        self.captains = {}
        self.mates = {}
        self.permits = {}
        self.charters = {}
        self.slot_reservations = {}
        self.crew_assignments = {}
        self.bookings = {}
        self.customers = {}
        self.add_on_lines = {}
        self.catch_reports = {}
        # Test-driving clock: when None, use real wall clock.
        self._clock = None
        # Monotonic creation sequence to keep stable insertion ordering for lists.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        """Current UTC instant the system reasons about (test clock or wall)."""
        if self._clock is not None:
            return self._clock
        return datetime.now(timezone.utc)

    def set_clock(self, dt):
        self._clock = dt


db = Store()


def new_id():
    return str(uuid.uuid4())


# Entities that carry updated_at + version (PRD 2.4): all except Permit, CatchReport.
def base_versioned():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def base_id_only():
    """For Permit and CatchReport: id + created_at, no updated_at/version."""
    return {
        "id": new_id(),
        "created_at": now_iso(),
    }


def touch(entity):
    """Bump updated_at and version on a versioned entity."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1
