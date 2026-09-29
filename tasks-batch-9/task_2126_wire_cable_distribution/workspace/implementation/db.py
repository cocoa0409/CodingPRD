"""In-memory data store. Starts completely empty on every boot -- nothing is
seeded, preloaded or hardcoded; every entity is created through the API."""
import uuid

import clock

_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


class Store(dict):
    """Ordered id -> record map."""

    def add(self, rec):
        self[rec["id"]] = rec
        return rec

    def values_ordered(self):
        """Every record in creation order (created_at ASC, insertion order as tie-break)."""
        return sorted(self.values(), key=lambda r: (r["created_at"], r["_seq"]))


branches = Store()
customers = Store()
products = Store()
copper_index_entries = Store()
trucks = Store()
reels = Store()
quotes = Store()
quote_lines = Store()
sales_orders = Store()
order_lines = Store()
allocations = Store()
delivery_runs = Store()

ALL_STORES = [
    branches, customers, products, copper_index_entries, trucks, reels,
    quotes, quote_lines, sales_orders, order_lines, allocations, delivery_runs,
]


def reset():
    for store in ALL_STORES:
        store.clear()
    _seq["n"] = 0
    clock.reset()


def base_record(versioned=True):
    stamp = clock.iso_now()
    rec = {"id": new_id(), "created_at": stamp, "_seq": next_seq()}
    if versioned:
        rec["updated_at"] = stamp
        rec["version"] = 1
    return rec


def touch(rec):
    """Advance a resource's version and updated_at exactly as a direct write would."""
    if rec is not None and "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = clock.iso_now()
    return rec


def sort_key(rec):
    return (rec["created_at"], rec["_seq"])
