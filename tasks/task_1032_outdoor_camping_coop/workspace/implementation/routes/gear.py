from flask import Blueprint, request

import core
from core import (
    db, ok, get_body, req_str, req_int, opt_int, opt_bool, opt_enum, req_enum,
    fetch, authenticate, authorize, new_common, serialize,
    sorted_by_created, paginate,
)

bp = Blueprint("gear", __name__)

SKU_CATEGORIES = {"TENT", "BACKPACK", "KAYAK", "STOVE", "APPAREL"}
UNIT_GRADES = {"NEW", "GOOD", "FAIR"}
UNIT_STATUSES = {"AVAILABLE", "RENTED_OUT"}


# ------------------------------- Gear SKUs
@bp.route("/coop/gear-skus", methods=["POST"])
def create_gear_sku():
    uid, role = authenticate()
    authorize(role, {"StoreStaff"})
    data = get_body()
    name = req_str(data, "name")
    category = req_enum(data, "category", SKU_CATEGORIES)
    retail_price_cents = req_int(data, "retail_price_cents", min_value=0)
    rentable = opt_bool(data, "rentable", False)
    daily_rental_rate_cents = opt_int(data, "daily_rental_rate_cents", 0, min_value=0)

    sku = new_common()
    sku.update({
        "name": name,
        "category": category,
        "retail_price_cents": retail_price_cents,
        "rentable": rentable,
        "daily_rental_rate_cents": daily_rental_rate_cents,
    })
    db.gear_skus[sku["id"]] = sku
    return ok(serialize(sku), status=201)


@bp.route("/coop/gear-skus/<sid>", methods=["GET"])
def get_gear_sku(sid):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    sku = fetch("gear_skus", sid)
    return ok(serialize(sku))


# ------------------------------- Gear Units
@bp.route("/coop/gear-units", methods=["POST"])
def create_gear_unit():
    uid, role = authenticate()
    authorize(role, {"StoreStaff"})
    data = get_body()
    gear_sku_id = req_str(data, "gear_sku_id")
    serial_number = req_str(data, "serial_number")
    condition_grade = opt_enum(data, "condition_grade", UNIT_GRADES, "GOOD")
    # existence of parent SKU
    fetch("gear_skus", gear_sku_id)

    unit = new_common()
    unit.update({
        "gear_sku_id": gear_sku_id,
        "serial_number": serial_number,
        "condition_grade": condition_grade,
        "status": "AVAILABLE",
    })
    db.gear_units[unit["id"]] = unit
    return ok(serialize(unit), status=201)


@bp.route("/coop/gear-units/<uid_>", methods=["GET"])
def get_gear_unit(uid_):
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    unit = fetch("gear_units", uid_)
    return ok(serialize(unit))


@bp.route("/coop/gear-units", methods=["GET"])
def list_gear_units():
    uid, role = authenticate()
    authorize(role, {"Member", "StoreStaff"})
    items = list(db.gear_units.values())
    gear_sku_id = request.args.get("gear_sku_id")
    status = request.args.get("status")
    if gear_sku_id is not None:
        items = [u for u in items if u["gear_sku_id"] == gear_sku_id]
    if status is not None:
        items = [u for u in items if u["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return ok(page, is_array=True, pagination=meta)
