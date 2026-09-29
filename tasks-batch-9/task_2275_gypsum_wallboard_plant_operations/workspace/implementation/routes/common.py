"""Shared route plumbing: path resolution (PRD 2.11 band 3), body reference
resolution (band 5) and list filtering (PRD 2.3)."""

from flask import request

from db import db, ordered
from errors import fail
from response import paged


# ---------------------------------------------------- path resolution (band 3)
def require_plant(plant_id):
    plant = db.plants.get(plant_id)
    if plant is None:
        fail("ERR_PLANT_NOT_FOUND", "plant %s does not exist" % plant_id)
    return plant


def require_lot(lot_id):
    lot = db.gypsum_lots.get(lot_id)
    if lot is None:
        fail("ERR_LOT_NOT_FOUND", "gypsum lot %s does not exist" % lot_id)
    return lot


def require_batch(batch_id):
    batch = db.calciner_batches.get(batch_id)
    if batch is None:
        fail("ERR_BATCH_NOT_FOUND", "calciner batch %s does not exist" % batch_id)
    return batch


def require_run(run_id):
    run = db.production_runs.get(run_id)
    if run is None:
        fail("ERR_RUN_NOT_FOUND", "production run %s does not exist" % run_id)
    return run


def require_outage(outage_id):
    outage = db.maintenance_outages.get(outage_id)
    if outage is None:
        fail("ERR_OUTAGE_NOT_FOUND", "maintenance outage %s does not exist" % outage_id)
    return outage


def require_load_order(load_order_id):
    load = db.load_orders.get(load_order_id)
    if load is None:
        fail("ERR_LOAD_ORDER_NOT_FOUND", "load order %s does not exist" % load_order_id)
    return load


def require_row(collection, row_id, label):
    row = collection.get(row_id)
    if row is None:
        fail("ERR_NOT_FOUND", "%s %s does not exist" % (label, row_id))
    return row


# ----------------------------------------- body reference resolution (band 5)
def require_ref(collection, row_id, label):
    row = collection.get(row_id)
    if row is None:
        fail("ERR_REFERENCE_NOT_FOUND", "%s %s does not exist" % (label, row_id))
    return row


# -------------------------------------------------------------------- listing
def _matches(entity, key, raw):
    value = entity.get(key)
    if isinstance(value, bool):
        lowered = raw.strip().lower()
        if lowered in ("true", "1"):
            return value is True
        if lowered in ("false", "0"):
            return value is False
        return False
    if value is None:
        return False
    return str(value) == raw


def list_collection(collection, filters=(), base=None):
    """Order by created_at ascending, apply the declared string filters, paginate."""
    items = base if base is not None else ordered(collection)
    for key in filters:
        raw = request.args.get(key)
        if raw is None or raw == "":
            continue
        items = [e for e in items if _matches(e, key, raw)]
    return paged(items)
