"""In-memory data store. Boots empty every process; nothing is seeded."""
import itertools
import threading
import uuid
from datetime import datetime, timezone

BOOT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.fleets = {}
        self.rate_cards = {}
        self.vehicles = {}
        self.technicians = {}
        self.service_calls = {}
        self.dispatches = {}
        self.van_stock = {}
        self.estimates = {}
        self.part_usages = {}
        self.tow_orders = {}
        self.warranty_claims = {}
        self.inspection_defects = {}
        self.invoices = {}
        self.payments = {}
        self.repeat_cases = {}
        self.restock_requests = {}
        self.call_events = {}
        self.spend_adjustments = {}
        self.clock = BOOT_CLOCK
        self.seq = itertools.count(1)          # global creation order
        self.invoice_seq = itertools.count(1)  # INV-000001 ...
        self.lock = threading.RLock()


store = Store()


def new_id():
    return str(uuid.uuid4())


def new_record():
    """Common system fields scaffold for a primary resource."""
    return {"id": new_id(), "version": 1, "_seq": next(store.seq)}


def touch(rec, wall_now=None):
    """Refresh updated_at and bump version on a mutation."""
    rec["version"] = rec.get("version", 1) + 1
    rec["_updated"] = wall_now
