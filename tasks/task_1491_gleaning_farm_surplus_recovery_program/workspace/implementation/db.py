"""In-memory data store. Starts completely empty on every boot — no seeding."""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.farms = {}
        self.offers = {}
        self.volunteers = {}
        self.waivers = {}
        self.agencies = {}
        self.events = {}
        self.assignments = {}
        self.lots = {}
        self.distributions = {}
        self.containers = {}
        self.vehicles = {}
        self.templogs = {}
        self.incidents = {}
        self.receipts = {}
        self.reports = {}
        self.seq = 0  # monotonic insertion counter for stable created_at ordering
        # Logical clock — PRD §2.5: startup instant is exactly 2026-08-01T00:00:00Z
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def now():
    return store.clock


def new_id():
    return str(uuid.uuid4())


def stamp_new(rec, mutable=True):
    """Attach system fields. Immutable records (Waiver, TempLog, DonationReceipt)
    carry only id + created_at (PRD §2.4)."""
    rec["id"] = new_id()
    store.seq += 1
    rec["_seq"] = store.seq
    rec["created_at"] = now()
    if mutable:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version (PRD §2.10)."""
    rec["updated_at"] = now()
    rec["version"] += 1
