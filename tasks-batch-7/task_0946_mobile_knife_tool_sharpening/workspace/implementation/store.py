"""In-memory data store.

Plain Python dicts keyed by id.  Nothing is persisted, nothing is seeded: the
store is empty on every boot and every row is created through the declared API
surface.
"""

import itertools
import uuid

import clock as clockmod

COLLECTIONS = (
    "accounts",
    "plan_tiers",
    "subscriptions",
    "item_class_specs",
    "service_requests",
    "request_items",
    "technicians",
    "vans",
    "route_runs",
    "route_stops",
    "locker_compartments",
    "bench_days",
    "loaner_units",
    "loaner_issues",
    "warranty_claims",
    "invoices",
    "invoice_lines",
    "payments",
    "allowance_entries",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def stamp_new(record, versioned=True):
    """Attach the common creation fields (PRD 2.4)."""
    record["id"] = new_id()
    record["created_at"] = clockmod.now()
    record["_seq"] = db.next_seq()
    if versioned:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and increment version on a mutated row (PRD 2.4)."""
    if "version" in record:
        record["updated_at"] = clockmod.now()
        record["version"] += 1
    return record


def order_key(record):
    """Default list ordering: created_at ascending, stable by insertion."""
    return (record["created_at"], record["_seq"])


def sorted_rows(rows):
    return sorted(rows, key=order_key)
