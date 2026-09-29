"""In-memory data store.

The store is EMPTY on every boot. Nothing is seeded, preloaded or hardcoded;
every entity is created through the declared API surface.
"""
import itertools
import uuid

from flask import g

import clock

RESERVING_STATUSES = ("CONFIRMED", "IN_TRANSIT", "PARTIALLY_RECEIVED")
LOT_LIVE_STATUSES = ("ACTIVE", "PARTIALLY_REMOVED")
LOT_ROLLUP_STATUSES = ("ACTIVE", "PARTIALLY_REMOVED", "DEPLETED")


class Store:
    def __init__(self):
        self.sellers = {}
        self.fcs = {}
        self.listings = {}
        self.quotas = {}
        self.plans = {}
        self.line_items = {}
        self.lots = {}
        self.assessments = {}
        self.removals = {}
        self.claims = {}
        self.forecasts = {}
        self.mcf_orders = {}
        self.billing_run_sequence = 0
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Store()


# --------------------------------------------------------------------------
# request-scoped mutation bookkeeping
# --------------------------------------------------------------------------

def begin_request():
    g.dirty = {}
    g.created = set()


def mark_dirty(entity):
    if entity is None:
        return
    store = getattr(g, "dirty", None)
    if store is None:
        return
    store[id(entity)] = entity


def mark_created(entity):
    created = getattr(g, "created", None)
    if created is not None:
        created.add(id(entity))


def set_field(entity, key, value):
    if entity.get(key) != value:
        entity[key] = value
        mark_dirty(entity)
        return True
    return False


def flush():
    """One updated_at refresh + one version increment per mutated resource."""
    store = getattr(g, "dirty", None)
    if not store:
        return
    created = getattr(g, "created", set())
    stamp = clock.now()
    for key, entity in store.items():
        if key in created:
            continue
        if "version" not in entity:
            continue
        entity["updated_at"] = stamp
        entity["version"] = entity["version"] + 1


def new_row(with_common=True):
    row = {"id": str(uuid.uuid4()), "created_at": clock.now(), "_seq": db.next_seq()}
    if with_common:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


# --------------------------------------------------------------------------
# lookup helpers
# --------------------------------------------------------------------------

def order_asc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def order_desc(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=True)


def seller_plans(seller_id):
    return [p for p in db.plans.values() if p["seller_account_id"] == seller_id]


def plan_lines(plan_id):
    return order_asc([li for li in db.line_items.values() if li["shipment_plan_id"] == plan_id])


def listing_lots(listing_id):
    return order_asc([l for l in db.lots.values() if l["sku_listing_id"] == listing_id])


def seller_listings(seller_id):
    return order_asc([l for l in db.listings.values() if l["seller_account_id"] == seller_id])


def seller_lots(seller_id):
    listing_ids = {l["id"] for l in db.listings.values() if l["seller_account_id"] == seller_id}
    return order_asc([l for l in db.lots.values() if l["sku_listing_id"] in listing_ids])


def active_quota(seller_id):
    for q in order_desc([q for q in db.quotas.values() if q["seller_account_id"] == seller_id]):
        if q["status"] == "ACTIVE":
            return q
    return None


def lot_seller(lot):
    listing = db.listings.get(lot["sku_listing_id"])
    if listing is None:
        return None
    return db.sellers.get(listing["seller_account_id"])
