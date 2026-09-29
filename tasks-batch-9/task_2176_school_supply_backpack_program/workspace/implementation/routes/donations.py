"""In-kind donation batches and the inventory ledger."""
from flask import Blueprint

import derive
import find
import response as resp
import validators as v
from db import base_record, db, sort_records, touch
from errors import ApiError
from middleware import (ALL_ROLES, SITE_COORDINATOR, WAREHOUSE_LEAD, auth,
                        site_scope)

bp = Blueprint("donations", __name__)

WAREHOUSE_ONLY_TARGETS = ("ACCEPTED", "QUARANTINED", "REMEDIATED", "DISCARDED")


@bp.post("/donation-batches")
def create_batch():
    user_id, role = auth([SITE_COORDINATOR])
    data = v.body()
    site_id = v.req_id(data, "collection_site_id")
    item_id = v.req_id(data, "supply_item_id")
    qty_declared = v.req_int(data, "qty_declared", minimum=1)
    condition = v.req_enum(data, "condition", v.CONDITIONS)
    sealed = v.opt_bool(data, "sealed", False)

    site = find.site(site_id)
    item = find.supply_item(item_id)
    site_scope(role, user_id, site["id"])

    if not item["catalog_active"]:
        raise ApiError("ERR_ITEM_INACTIVE")

    cycle = db.drive_cycles.get(site["drive_cycle_id"])
    if cycle is None or cycle["status"] != "COLLECTING":
        raise ApiError("ERR_CYCLE_PHASE_INVALID")

    rec = base_record()
    rec.update({
        "collection_site_id": site["id"],
        "supply_item_id": item["id"],
        "qty_declared": qty_declared,
        "condition": condition,
        "sealed": sealed,
        "status": "RECEIVED",
        "qty_accepted": 0,
        "qty_rejected": 0,
        "hold_reason": None,
    })
    db.donation_batches[rec["id"]] = rec

    derive.refresh_in_transit(cycle["id"], item["id"])
    derive.refresh_events_for_item(cycle["id"], item["id"])
    return resp.ok(rec, 201)


@bp.get("/donation-batches/<batch_id>")
def read_batch(batch_id):
    auth(ALL_ROLES)
    return resp.ok(find.batch(batch_id))


@bp.get("/donation-batches")
def list_batches():
    auth(ALL_ROLES)
    limit, offset = v.pagination()
    site_id = v.query_id("collection_site_id")
    item_id = v.query_id("supply_item_id")
    status = v.query_enum("status", v.BATCH_STATUSES)
    rows = list(db.donation_batches.values())
    if site_id:
        rows = [r for r in rows if r["collection_site_id"] == site_id]
    if item_id:
        rows = [r for r in rows if r["supply_item_id"] == item_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return resp.listing(sort_records(rows), limit, offset)


def _hygiene_ok(batch, item):
    if not item["hygiene_sealed_required"]:
        return True
    return bool(batch["sealed"]) and batch["condition"] == "NEW"


@bp.post("/donation-batches/<batch_id>/transitions")
def move_batch(batch_id):
    user_id, role = auth([SITE_COORDINATOR, WAREHOUSE_LEAD])
    data = v.body()
    target = v.target_status(data)
    if target in WAREHOUSE_ONLY_TARGETS and role != WAREHOUSE_LEAD:
        raise ApiError("ERR_UNAUTHORIZED")
    qty_rejected = v.opt_int(data, "qty_rejected", 0, minimum=0)
    hold_reason = v.opt_str(data, "hold_reason", None)

    batch = find.batch(batch_id)
    site = db.collection_sites.get(batch["collection_site_id"])
    site_scope(role, user_id, batch["collection_site_id"])

    item = db.supply_items.get(batch["supply_item_id"])
    cycle = db.drive_cycles.get(site["drive_cycle_id"]) if site else None
    current = batch["status"]

    if target not in v.BATCH_STATUSES:
        raise ApiError("ERR_INVALID_BATCH_STATE")

    if target == "INSPECTED":
        if current != "RECEIVED":
            raise ApiError("ERR_INVALID_BATCH_STATE")
        if site is None or site["operational_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_BATCH_STATE")
        batch["status"] = "INSPECTED"
        derive.refresh_in_transit(cycle["id"], batch["supply_item_id"])
        derive.refresh_events_for_item(cycle["id"], batch["supply_item_id"])
        touch(batch)
    elif target == "ACCEPTED":
        if current not in ("INSPECTED", "REMEDIATED"):
            raise ApiError("ERR_INVALID_BATCH_STATE")
        if qty_rejected > batch["qty_declared"]:
            raise ApiError("ERR_INVALID_REQUEST",
                           "qty_rejected may not exceed qty_declared.")
        if not _hygiene_ok(batch, item):
            raise ApiError("ERR_UNSAFE_ITEM_CONDITION")
        if cycle is None or cycle["status"] not in ("COLLECTING", "SORTING"):
            raise ApiError("ERR_CYCLE_PHASE_INVALID")
        _acceptance_cascade(batch, site, cycle, qty_rejected)
    elif target == "QUARANTINED":
        if current != "INSPECTED":
            raise ApiError("ERR_INVALID_BATCH_STATE")
        batch["status"] = "QUARANTINED"
        batch["hold_reason"] = hold_reason
        derive.refresh_in_transit(cycle["id"], batch["supply_item_id"])
        derive.refresh_events_for_item(cycle["id"], batch["supply_item_id"])
        touch(batch)
    elif target == "REMEDIATED":
        if current != "QUARANTINED":
            raise ApiError("ERR_INVALID_BATCH_STATE")
        if not _hygiene_ok(batch, item):
            raise ApiError("ERR_UNSAFE_ITEM_CONDITION")
        batch["status"] = "REMEDIATED"
        batch["hold_reason"] = None
        derive.refresh_in_transit(cycle["id"], batch["supply_item_id"])
        derive.refresh_events_for_item(cycle["id"], batch["supply_item_id"])
        touch(batch)
    elif target == "DISCARDED":
        if current != "QUARANTINED":
            raise ApiError("ERR_INVALID_BATCH_STATE")
        batch["status"] = "DISCARDED"
        pos = derive.get_position(cycle["id"], batch["supply_item_id"], create=True)
        pos["damaged_qty"] += batch["qty_declared"]
        pos["adjustment_qty"] += batch["qty_declared"]
        pos["in_transit_qty"] = derive.compute_in_transit(
            cycle["id"], batch["supply_item_id"])
        touch(pos)
        derive.refresh_events_for_item(cycle["id"], batch["supply_item_id"])
        touch(batch)
    else:
        raise ApiError("ERR_INVALID_BATCH_STATE")

    return resp.ok(batch)


def _acceptance_cascade(batch, site, cycle, qty_rejected):
    item_id = batch["supply_item_id"]
    # HOP 1
    batch["qty_rejected"] = qty_rejected
    batch["qty_accepted"] = batch["qty_declared"] - qty_rejected
    batch["status"] = "ACCEPTED"
    # HOP 2
    pos = derive.get_position(cycle["id"], item_id, create=True)
    pos["on_hand_qty"] += batch["qty_accepted"]
    pos["accepted_donated_qty"] += batch["qty_declared"]
    pos["damaged_qty"] += qty_rejected
    pos["in_transit_qty"] = derive.compute_in_transit(cycle["id"], item_id)
    touch(pos)
    # HOP 3
    derive.recompute_cycle_inventory(cycle)
    touch(cycle)
    derive.recompute_site_accepted(site)
    touch(site)
    # HOP 4 + HOP 5
    derive.refresh_events_for_item(cycle["id"], item_id, promote=True)
    touch(batch)


# --------------------------------------------------------------------------
# InventoryPosition
# --------------------------------------------------------------------------
@bp.post("/inventory-positions/adjustments")
def adjust_position():
    auth([WAREHOUSE_LEAD])
    data = v.body()
    cycle_id = v.req_id(data, "drive_cycle_id")
    item_id = v.req_id(data, "supply_item_id")
    delta_on_hand = v.req_int(data, "delta_on_hand_qty")
    delta_damaged = v.opt_int(data, "delta_damaged_qty", 0)
    v.req_str(data, "reason")

    cycle = find.cycle(cycle_id)
    item = find.supply_item(item_id)

    existed = derive.get_position(cycle["id"], item["id"]) is not None
    pos = derive.get_position(cycle["id"], item["id"], create=True)
    if pos["on_hand_qty"] + delta_on_hand < 0:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY")

    pos["on_hand_qty"] += delta_on_hand
    pos["damaged_qty"] += delta_damaged
    pos["adjustment_qty"] += delta_on_hand + delta_damaged
    pos["in_transit_qty"] = derive.compute_in_transit(cycle["id"], item["id"])
    if existed:
        touch(pos)

    derive.recompute_cycle_inventory(cycle)
    derive.refresh_events_for_item(cycle["id"], item["id"], promote=True)
    derive.recompute_cycle_inventory(cycle)
    touch(cycle)
    return resp.ok(pos)


@bp.get("/inventory-positions/<position_id>")
def read_position(position_id):
    auth(ALL_ROLES)
    return resp.ok(find.position(position_id))


@bp.get("/inventory-positions")
def list_positions():
    auth(ALL_ROLES)
    limit, offset = v.pagination()
    cycle_id = v.query_id("drive_cycle_id")
    item_id = v.query_id("supply_item_id")
    rows = list(db.inventory_positions.values())
    if cycle_id:
        rows = [r for r in rows if r["drive_cycle_id"] == cycle_id]
    if item_id:
        rows = [r for r in rows if r["supply_item_id"] == item_id]
    return resp.listing(sort_records(rows), limit, offset)
