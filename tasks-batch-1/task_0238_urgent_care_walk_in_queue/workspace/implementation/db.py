"""In-memory data store. Starts empty on every boot (no seeding)."""
from util import new_uuid
import clock


class Store:
    def __init__(self):
        self.clinics = {}
        self.exam_rooms = {}
        self.providers = {}
        self.queue_entries = {}
        self.patients = {}
        self.coverages = {}
        self.visits = {}
        self.charges = {}
        self.occ_health_orders = {}
        self.referrals = {}
        self.discharge_instructions = {}


db = Store()


def stamp_create(record):
    """Attach common fields id/created_at/updated_at/version on creation."""
    ts = clock.now()
    record.setdefault("id", new_uuid())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """A mutation: refresh updated_at and bump version (PRD §2.4)."""
    record["updated_at"] = clock.now()
    record["version"] = record.get("version", 1) + 1
