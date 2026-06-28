"""In-memory data store. State is wiped on every process restart — no seeding,
no preloaded entities, no persistence. Tests build all data via the API."""
import uuid

from clock import clock


class DB:
    def __init__(self):
        # One dict per entity collection, keyed by id (UUID string, no prefix — PRD §2.4).
        self.subscription_plans = {}
        self.fleets = {}
        self.vehicles = {}
        self.applicants = {}
        self.subscriptions = {}
        self.billing_cycles = {}
        self.invoices = {}
        self.swap_requests = {}
        self.return_inspections = {}
        self.damage_line_items = {}
        self.couriers = {}
        self.delivery_slots = {}
        # Monotonic sequence to break created_at ties for deterministic sort order.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def new_id():
    # PRD §2.4: "a UUID with no type prefix".
    return str(uuid.uuid4())


def stamp_create(record, with_version=True):
    """Set system-managed common fields on create (PRD §2.4)."""
    now = clock.now_iso()
    record["id"] = new_id()
    record["created_at"] = now
    record["_seq"] = db.next_seq()
    if with_version:
        record["updated_at"] = now
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and increment version on mutation (PRD §2.4)."""
    record["updated_at"] = clock.now_iso()
    record["version"] = record.get("version", 1) + 1
