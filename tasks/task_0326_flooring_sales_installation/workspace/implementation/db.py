"""In-memory data store. Starts empty on every boot — no seeding."""
import threading
import uuid

import clock


class Store:
    """All entity collections keyed by id. In-memory only."""

    def __init__(self):
        self.lock = threading.RLock()
        self.products = {}
        self.jobs = {}
        self.estimates = {}
        self.material_orders = {}
        self.install_crews = {}
        self.install_slots = {}
        self.warranty_claims = {}
        self.customers = {}
        self.sales_reps = {}

    def new_id(self):
        return str(uuid.uuid4())


db = Store()


def stamp_create(record):
    """Set system fields on a freshly created common-fields entity."""
    ts = clock.iso(clock.now())
    record["id"] = db.new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def stamp_light_create(record):
    """Set system fields on a light entity (Customer/SalesRep): id + created_at only."""
    record["id"] = db.new_id()
    record["created_at"] = clock.iso(clock.now())
    return record


def touch(record):
    """Mark a common-fields entity as mutated: bump updated_at and version."""
    record["updated_at"] = clock.iso(clock.now())
    record["version"] = record["version"] + 1
    return record
