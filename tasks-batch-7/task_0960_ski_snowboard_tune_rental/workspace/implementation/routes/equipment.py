from flask import Blueprint, request

from auth import auth
from envelope import created, list_response, success
from errors import err
from store import db, new_entity, pub, touch
from validate import (GEAR_TYPES, INSPECT_OUTCOMES, TIERS, body, get_or_404,
                      req_enum, req_int, req_num, req_str)

bp = Blueprint("equipment", __name__)


@bp.post("/shop/equipment-items")
def create_equipment():
    auth("Manager")
    b = body()
    unit = new_entity({
        "gear_type": req_enum(b, "gear_type", GEAR_TYPES),
        "size_label": req_str(b, "size_label"),
        "tier": req_enum(b, "tier", TIERS),
        "status": "AVAILABLE",
        "din_min": req_num(b, "din_min"),
        "din_max": req_num(b, "din_max"),
        "purchase_price_cents": req_int(b, "purchase_price_cents", minimum=1),
        "base_daily_rate_cents": req_int(b, "base_daily_rate_cents", minimum=1),
        "accrued_rental_days": 0,
    })
    db.equipment_items[unit["id"]] = unit
    return created(pub(unit))


@bp.get("/shop/equipment-items/<eid>")
def get_equipment(eid):
    auth("Customer", "FrontDesk", "Technician", "Manager")
    unit = get_or_404(db.equipment_items, eid, "Equipment item")
    return success(pub(unit))


@bp.get("/shop/equipment-items")
def list_equipment():
    auth("Customer", "FrontDesk", "Technician", "Manager")
    items = list(db.equipment_items.values())
    status = request.args.get("status")
    gear_type = request.args.get("gear_type")
    tier = request.args.get("tier")
    if status is not None:
        items = [u for u in items if u["status"] == status]
    if gear_type is not None:
        items = [u for u in items if u["gear_type"] == gear_type]
    if tier is not None:
        items = [u for u in items if u["tier"] == tier]
    return list_response(items)


@bp.post("/shop/equipment-items/<eid>/retire")
def retire_equipment(eid):
    auth("Manager")
    unit = get_or_404(db.equipment_items, eid, "Equipment item")
    if unit["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Only an AVAILABLE unit can be retired")
    if any(i["equipment_item_id"] == eid and i["status"] == "ASSIGNED"
           for i in db.reservation_items.values()):
        raise err("ERR_INVALID_STATE",
                  "Unit is referenced by an assigned reservation line")
    unit["status"] = "RETIRED"
    touch(unit)
    return success(pub(unit))


@bp.post("/shop/equipment-items/<eid>/inspect")
def inspect_equipment(eid):
    auth("Technician", "Manager")
    unit = get_or_404(db.equipment_items, eid, "Equipment item")
    if unit["status"] != "AWAITING_INSPECTION":
        raise err("ERR_INVALID_STATE",
                  "Only a unit AWAITING_INSPECTION can be inspected")
    outcome = req_enum(body(), "outcome", INSPECT_OUTCOMES)
    unit["status"] = "AVAILABLE" if outcome == "PASS" else "IN_SERVICE"
    touch(unit)
    return success(pub(unit))


@bp.post("/shop/equipment-items/<eid>/service-complete")
def service_complete(eid):
    auth("Technician", "Manager")
    unit = get_or_404(db.equipment_items, eid, "Equipment item")
    if unit["status"] != "IN_SERVICE":
        raise err("ERR_INVALID_STATE",
                  "Only a unit IN_SERVICE can complete service")
    unit["status"] = "AVAILABLE"
    touch(unit)
    return success(pub(unit))
