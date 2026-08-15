"""Inventory lots and delivery slots (PRD 3.1)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_BRANCH_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND,
    ERR_LOT_NOT_FOUND,
    ERR_SLOT_NOT_FOUND,
    ERR_INVALID_REQUEST,
)
from middleware import authorized
from routes.helpers import body, body_field, render_list, render_one, require_int
from services.core import create_record, get_or_404, mutate

bp = Blueprint("inventory", __name__)

LOT_READ_ROLES = ["PlatformAdmin", "BranchManager", "SalesRep", "Dispatcher", "WarehouseClerk"]
SLOT_READ_ROLES = ["PlatformAdmin", "BranchManager", "Dispatcher", "Contractor"]
EQUIPMENT_TYPES = ("GROUND", "ROOFTOP_CONVEYOR", "CRANE")
WINDOWS = ("AM", "PM")


# ---------------------------------------------------------------------------
# Inventory lots
# ---------------------------------------------------------------------------

@bp.post("/roofing/branches/<bid>/inventory-lots")
def receive_lot(bid):
    """Receive stock: creates the lot or tops up an existing
    (branch, product, lot_code) lot (PRD 3.1)."""
    authorized(["WarehouseClerk", "PlatformAdmin"])
    branch = get_or_404("branches", bid, ERR_BRANCH_NOT_FOUND)
    data = body()
    product_id = body_field(data, "product_id", required=True)
    if db["products"].get(product_id) is None:
        raise_error(ERR_PRODUCT_NOT_FOUND, f"product {product_id} does not exist")
    lot_code = body_field(data, "lot_code", required=True)
    on_hand = require_int(body_field(data, "on_hand_bundles", required=True),
                          "on_hand_bundles", minimum=0)

    existing = None
    for lot in db["inventory_lots"].values():
        if (lot["branch_id"] == branch["id"] and lot["product_id"] == product_id
                and lot["lot_code"] == lot_code):
            existing = lot
            break
    if existing is not None:
        existing["on_hand_bundles"] += on_hand
        mutate(existing)
        return render_one("inventory_lots", existing, status=201)

    rec = create_record("inventory_lots", {
        "branch_id": branch["id"],
        "product_id": product_id,
        "lot_code": lot_code,
        "on_hand_bundles": on_hand,
        "reserved_bundles": 0,
    })
    return render_one("inventory_lots", rec, status=201)


@bp.get("/roofing/branches/<bid>/inventory-lots")
def list_branch_lots(bid):
    caller = authorized(LOT_READ_ROLES)
    branch = get_or_404("branches", bid, ERR_BRANCH_NOT_FOUND)
    lots = [l for l in db["inventory_lots"].values() if l["branch_id"] == branch["id"]]
    return render_list(caller, "inventory_lots",
                       filters={"product_id": request.args.get("product_id")},
                       base_records=lots)


@bp.get("/roofing/inventory-lots/<rid>")
def get_lot(rid):
    caller = authorized(LOT_READ_ROLES)
    rec = get_or_404("inventory_lots", rid, ERR_LOT_NOT_FOUND)
    return render_one("inventory_lots", rec)


@bp.get("/roofing/inventory-lots")
def list_lots():
    caller = authorized(LOT_READ_ROLES)
    return render_list(caller, "inventory_lots",
                       filters={"product_id": request.args.get("product_id"),
                                "branch_id": request.args.get("branch_id")})


# ---------------------------------------------------------------------------
# Delivery slots
# ---------------------------------------------------------------------------

@bp.post("/roofing/branches/<bid>/delivery-slots")
def create_slot(bid):
    authorized(["Dispatcher", "PlatformAdmin"])
    branch = get_or_404("branches", bid, ERR_BRANCH_NOT_FOUND)
    data = body()
    window = body_field(data, "window", required=True)
    equipment_type = body_field(data, "equipment_type", required=True)
    if window not in WINDOWS:
        raise_error(ERR_INVALID_REQUEST, "window must be AM or PM")
    if equipment_type not in EQUIPMENT_TYPES:
        raise_error(ERR_INVALID_REQUEST, "equipment_type must be GROUND, ROOFTOP_CONVEYOR or CRANE")
    rec = create_record("delivery_slots", {
        "branch_id": branch["id"],
        "slot_date": body_field(data, "slot_date", required=True),
        "window": window,
        "equipment_type": equipment_type,
        "capacity": require_int(body_field(data, "capacity", required=True), "capacity", minimum=0),
        "booked_count": 0,
    })
    return render_one("delivery_slots", rec, status=201)


@bp.get("/roofing/branches/<bid>/delivery-slots")
def list_branch_slots(bid):
    caller = authorized(SLOT_READ_ROLES)
    branch = get_or_404("branches", bid, ERR_BRANCH_NOT_FOUND)
    slots = [s for s in db["delivery_slots"].values() if s["branch_id"] == branch["id"]]
    return render_list(caller, "delivery_slots",
                       filters={"slot_date": request.args.get("slot_date"),
                                "equipment_type": request.args.get("equipment_type")},
                       base_records=slots)


@bp.get("/roofing/delivery-slots/<rid>")
def get_slot(rid):
    caller = authorized(SLOT_READ_ROLES)
    rec = get_or_404("delivery_slots", rid, ERR_SLOT_NOT_FOUND)
    return render_one("delivery_slots", rec)
