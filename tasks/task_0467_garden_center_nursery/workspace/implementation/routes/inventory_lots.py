"""InventoryLot endpoints: receive, read, release, quarantine, care-log."""
from flask import Blueprint, request

import errors
from db import db, base_versioned, base_ledger, touch, now_iso
from errors import err
from lookups import body, get_product, get_lot
from middleware import require_roles, parse_pagination, paginate
from response import ok, created, ok_list
from services.inventory import recompute_lot, maybe_deplete
from validation import req_int_gt, req_int_min, req_enum, opt_int, opt_str

bp = Blueprint("inventory_lots", __name__)

CARE_TYPES = {"WATERING", "TREATMENT", "INSPECTION", "SHRINK_LOSS"}


def lot_view(l):
    return {
        "id": l["id"],
        "product_id": l["product_id"],
        "nursery_id": l["nursery_id"],
        "special_order_id": l["special_order_id"],
        "received_qty": l["received_qty"],
        "unit_cost_cents": l["unit_cost_cents"],
        "qty_on_hand": l["qty_on_hand"],
        "reserved_qty": l["reserved_qty"],
        "shrink_qty": l["shrink_qty"],
        "sold_qty": l["sold_qty"],
        "provisional_shrink_value_cents": l["provisional_shrink_value_cents"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def care_log_view(c):
    return {
        "id": c["id"],
        "inventory_lot_id": c["inventory_lot_id"],
        "entry_type": c["entry_type"],
        "qty_lost": c["qty_lost"],
        "note": c["note"],
        "logged_at": c["logged_at"],
        "created_at": c["created_at"],
    }


def mint_lot(product, received_qty, unit_cost_cents, special_order_id=None):
    """Create a QUARANTINE lot (shared by receive + special-order receive)."""
    l = base_versioned()
    l.update({
        "product_id": product["id"],
        "nursery_id": product["nursery_id"],
        "special_order_id": special_order_id,
        "received_qty": received_qty,
        "unit_cost_cents": unit_cost_cents,
        "reserved_qty": 0,
        "shrink_qty": 0,
        "sold_qty": 0,
        "qty_on_hand": received_qty,
        "provisional_shrink_value_cents": 0,
        "status": "QUARANTINE",
    })
    recompute_lot(l)
    db.inventory_lots[l["id"]] = l
    return l


@bp.post("/products/<product_id>/inventory-lots")
@require_roles("InventoryManager")
def receive_lot(product_id):
    product = get_product(product_id)
    data = body()
    received_qty = req_int_gt(data, "received_qty", 0)
    unit_cost = req_int_min(data, "unit_cost_cents", 0)
    l = mint_lot(product, received_qty, unit_cost, None)
    return created(lot_view(l))


@bp.get("/inventory-lots/<lot_id>")
@require_roles("InventoryManager", "SalesClerk")
def read_lot(lot_id):
    l = get_lot(lot_id)
    return ok(lot_view(l))


@bp.post("/inventory-lots/<lot_id>/release")
@require_roles("InventoryManager")
def release_lot(lot_id):
    l = get_lot(lot_id)
    if l["status"] != "QUARANTINE":
        err(errors.ERR_LOT_NOT_QUARANTINED, "lot not in QUARANTINE")
    if l["qty_on_hand"] <= 0:
        err(errors.ERR_LOT_EMPTY, "lot has no sellable quantity")
    l["status"] = "AVAILABLE"
    touch(l)
    return ok(lot_view(l))


@bp.post("/inventory-lots/<lot_id>/quarantine")
@require_roles("InventoryManager")
def quarantine_lot(lot_id):
    l = get_lot(lot_id)
    if l["status"] != "AVAILABLE":
        err(errors.ERR_LOT_NOT_AVAILABLE, "lot not in AVAILABLE")
    if l["reserved_qty"] != 0:
        err(errors.ERR_LOT_HAS_RESERVATIONS, "lot has reservations")
    l["status"] = "QUARANTINE"
    touch(l)
    return ok(lot_view(l))


@bp.post("/inventory-lots/<lot_id>/care-log")
@require_roles("InventoryManager")
def add_care_log(lot_id):
    l = get_lot(lot_id)
    data = body()
    entry_type = req_enum(data, "entry_type", CARE_TYPES)
    qty_lost = opt_int(data, "qty_lost", 0)
    note = opt_str(data, "note", "")

    if entry_type == "SHRINK_LOSS":
        if qty_lost <= 0:
            err(errors.ERR_INVALID_REQUEST, "SHRINK_LOSS requires qty_lost > 0")
    else:
        if qty_lost != 0:
            err(errors.ERR_INVALID_REQUEST, "non-SHRINK_LOSS requires qty_lost == 0")

    entry = base_ledger()
    entry.update({
        "inventory_lot_id": l["id"],
        "entry_type": entry_type,
        "qty_lost": qty_lost,
        "note": note,
        "logged_at": now_iso(),
    })
    db.care_log_entries[entry["id"]] = entry

    if entry_type == "SHRINK_LOSS":
        l["shrink_qty"] += qty_lost
        recompute_lot(l)
        touch(l)
        maybe_deplete(l)

    return created(care_log_view(entry))


@bp.get("/inventory-lots/<lot_id>/care-log")
@require_roles("InventoryManager", "SalesClerk")
def list_care_log(lot_id):
    get_lot(lot_id)
    limit, offset = parse_pagination()
    entry_type = request.args.get("entry_type")
    items = [c for c in db.care_log_entries.values()
             if c["inventory_lot_id"] == lot_id]
    if entry_type is not None:
        items = [c for c in items if c["entry_type"] == entry_type]
    items.sort(key=lambda c: c["_seq"])
    total = len(items)
    page = paginate(items, limit, offset)
    return ok_list([care_log_view(c) for c in page], limit, offset, total)
