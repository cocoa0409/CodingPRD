"""In-memory data store. Starts empty on every boot — NO seeding."""
import itertools
import threading
import uuid

from response import now_iso


class Store:
    def __init__(self):
        # Each collection is a dict keyed by id.
        self.facilities = {}
        self.operating_rooms = {}
        self.recovery_bays = {}
        self.anesthesiologists = {}
        self.surgeons = {}
        self.procedures = {}
        self.supply_items = {}
        self.surgical_days = {}
        self.surgeon_blocks = {}
        self.surgical_cases = {}
        self.patients = {}
        self.case_implants = {}
        self.clearance_checks = {}
        # Monotonic sequence used to break created_at ties deterministically.
        self._seq = itertools.count(1)
        self.lock = threading.RLock()

    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)


db = Store()


def stamp_common(record):
    """Attach common lifecycle fields on create (id, created_at, updated_at, version)."""
    ts = now_iso()
    record.setdefault("id", db.new_id())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Bump updated_at and version on mutation."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
