"""In-memory data store. Starts empty on every boot; no seeding."""
import uuid

from response import now_iso_millis


class Store:
    def __init__(self):
        self.agencies = {}
        self.customers = {}
        self.suppliers = {}
        self.tour_packages = {}
        self.bookings = {}
        self.travelers = {}
        self.components = {}
        self.milestones = {}
        self.payments = {}
        self.insurance_policies = {}
        self.cancellation_records = {}

    def new_id(self):
        return str(uuid.uuid4())


db = Store()


def stamp_create(entity):
    """Set system-managed common fields on create."""
    ts = now_iso_millis()
    entity["id"] = db.new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version on mutation (PRD §2.5)."""
    entity["updated_at"] = now_iso_millis()
    entity["version"] = entity.get("version", 1) + 1
    return entity
