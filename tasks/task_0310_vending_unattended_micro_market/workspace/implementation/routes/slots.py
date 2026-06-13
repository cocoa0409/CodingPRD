"""PlanogramSlot endpoints (PRD 3.3) and slot-scoped lot listing."""
from flask import Blueprint, request

from common import (get_json_body, get_or_404, list_response, require_int,
                    require_str)
from db import db, stamp_create, touch
from errors import ApiError
from middleware import require_roles
from response import object_response
from services import serialize
from services.inventory import rederive_machine_stock

bp = Blueprint("slots", __name__)

ALL_ROLES = ("FieldOps", "RouteDriver", "HostManager", "FinanceClerk")


@bp.route("/operations/machines/<machine_id>/slots", methods=["POST"])
@require_roles("FieldOps")
def add_slot(machine_id):
    machine = get_or_404("machines", machine_id)
    body = get_json_body()
    product_id = require_str(body, "product_id")
    slot_code = require_str(body, "slot_code")
    capacity = require_int(body, "capacity")
    par_level = require_int(body, "par_level")
    price_cents = require_int(body, "price_cents")

    # FK existence (priority 4)
    product = db.products.get(product_id)
    if product is None:
        raise ApiError("ERR_PRODUCT_NOT_FOUND", "Product not found")

    # business constraint (priority 14): product must be ACTIVE
    if product["status"] == "DISCONTINUED":
        raise ApiError("ERR_PRODUCT_DISCONTINUED",
                       "Cannot assign a discontinued product to a slot")

    # business constraint (priority 12): slot config validated as a unit
    if capacity <= 0 or price_cents <= 0 or par_level <= 0 or par_level > capacity:
        raise ApiError("ERR_INVALID_SLOT_CONFIG", "Invalid slot configuration")
    for s in db.slots.values():
        if s["machine_id"] == machine_id and s["slot_code"] == slot_code:
            raise ApiError("ERR_INVALID_SLOT_CONFIG",
                           "slot_code must be unique within the machine")

    obj = {
        "machine_id": machine_id,
        "product_id": product_id,
        "slot_code": slot_code,
        "capacity": capacity,
        "par_level": par_level,
        "price_cents": price_cents,
        "on_hand": 0,
        "status": "ACTIVE",
    }
    stamp_create(obj)
    db.slots[obj["id"]] = obj

    # adding a slot triggers re-derivation of the machine's stock_status
    rederive_machine_stock(machine)
    return object_response(serialize.slot(obj), 201)


@bp.route("/operations/machines/<machine_id>/slots", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_machine_slots(machine_id):
    get_or_404("machines", machine_id)
    rows = [s for s in db.slots.values() if s["machine_id"] == machine_id]
    return list_response(rows, serialize.slot)


@bp.route("/operations/slots", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_slots():
    rows = list(db.slots.values())
    machine_id = request.args.get("machine_id")
    product_id = request.args.get("product_id")
    if machine_id is not None:
        rows = [s for s in rows if s["machine_id"] == machine_id]
    if product_id is not None:
        rows = [s for s in rows if s["product_id"] == product_id]
    return list_response(rows, serialize.slot)


@bp.route("/operations/slots/<slot_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_slot(slot_id):
    obj = get_or_404("slots", slot_id)
    return object_response(serialize.slot(obj))


@bp.route("/operations/slots/<slot_id>/price", methods=["PATCH"])
@require_roles("FieldOps")
def change_price(slot_id):
    obj = get_or_404("slots", slot_id)
    body = get_json_body()
    price_cents = require_int(body, "price_cents")
    if price_cents <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "price_cents must be > 0")
    obj["price_cents"] = price_cents
    touch(obj)
    return object_response(serialize.slot(obj))


@bp.route("/operations/slots/<slot_id>/lots", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_slot_lots(slot_id):
    get_or_404("slots", slot_id)
    rows = [l for l in db.lots.values() if l["slot_id"] == slot_id]
    return list_response(rows, serialize.lot)
