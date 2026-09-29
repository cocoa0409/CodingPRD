"""In-memory data store.

The store starts completely empty on every boot.  Nothing is seeded, preloaded
or hardcoded: every entity is created by clients through the declared
endpoints.
"""

import itertools
import uuid

import clock

_seq = itertools.count(1)

COLLECTIONS = (
    "metal_price_quotes",
    "rod_purchase_lots",
    "compounds",
    "listing_certifications",
    "factory_inspections",
    "catalog_products",
    "customers",
    "customer_orders",
    "production_lots",
    "cable_tests",
    "reels",
    "shipments",
    "reel_returns",
)


class Store(dict):
    def __init__(self):
        super().__init__()
        for name in COLLECTIONS:
            self[name] = {}

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:  # pragma: no cover
            raise AttributeError(item)


db = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def new_record(common_fields=True):
    """Create the identity/audit skeleton every record carries (PRD 2.4)."""
    ts = clock.now_iso()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": next_seq(),
    }
    if common_fields:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """Refresh updated_at and increment version by exactly 1 (PRD 2.4)."""
    if "version" in rec:
        rec["updated_at"] = clock.now_iso()
        rec["version"] = rec["version"] + 1
    return rec


def sort_created(rows):
    """Ascending created_at with insertion order as the deterministic tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def all_sorted(collection):
    return sort_created(list(collection.values()))
