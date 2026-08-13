"""In-memory data store + logical clock.

Storage is process-local dicts keyed by id. No disk persistence, no seeding.
The store starts completely empty on every boot.
"""
import itertools
import uuid
from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.price_configs = {}
        self.variety_configs = {}
        self.fields = {}
        self.reseed_plans = {}
        self.harvest_batches = {}
        self.customers = {}
        self.crews = {}
        self.quotes = {}
        self.orders = {}
        self.payments = {}
        self.delivery_checks = {}
        self.crew_referrals = {}
        self.warranty_claims = {}
        self.watering_logs = {}
        self.truck_blocks = {}
        # Logical clock: reads exactly 2026-08-01T00:00:00Z before any set call.
        self.clock = DEFAULT_CLOCK
        self.last_stamp = None
        self.seq = itertools.count(1)


store = Store()


def now():
    """Current logical clock instant (aware, UTC)."""
    return store.clock


def today():
    return store.clock.date()


def new_id():
    return str(uuid.uuid4())


def stamp():
    """Monotonic unique timestamp (ms precision) derived from the logical clock.

    Guarantees uniqueness per row even when the logical clock does not advance
    between writes, so created_at ordering is total.
    """
    n = store.clock
    if store.last_stamp is not None and n <= store.last_stamp:
        n = store.last_stamp + timedelta(milliseconds=1)
    store.last_stamp = n
    return n


def common_fields():
    """System-managed properties for primary resources."""
    ts = stamp()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(store.seq),
    }


def sub_fields():
    """Append-only sub-resources carry only id + created_at."""
    ts = stamp()
    return {"id": new_id(), "created_at": ts, "_seq": next(store.seq)}


def bump(entity):
    """Register a modification: version += 1, updated_at refreshed."""
    entity["version"] += 1
    entity["updated_at"] = stamp()
