"""EquipmentUnit endpoints."""

from flask import Blueprint, request

import db
from errors import err_not_found, err_invalid_request, err_invalid_state
from middleware import require_role, get_json_body, get_pagination
from response import success_object, success_list
from services.core import stamp_new, touch, serialize, audit

bp = Blueprint("equipment_units", __name__)

READ_ROLES = ("PlatformAdmin", "InventoryManager", "SalesRep", "InstallCoordinator")


@bp.post("/stairlift-ops/equipment-units")
def create_equipment_unit():
    require_role("InventoryManager", "PlatformAdmin")
    body = get_json_body(["model_code", "serial_number"])
    model_code = body["model_code"]
    serial = body["serial_number"]
    if not isinstance(model_code, str) or not isinstance(serial, str):
        raise err_invalid_request("model_code and serial_number must be strings")
    if model_code not in db.product_models_by_code:
        raise err_not_found("ProductModel not found")
    unit = {
        "model_code": model_code,
        "serial_number": serial,
        "condition_grade": "NEW",
        "status": "IN_STOCK",
        "acquired_at": db.now_iso(),
        "lifetime_rental_months": 0,
    }
    stamp_new(unit)
    db.equipment_units[unit["id"]] = unit
    db.equipment_by_serial[serial] = unit["id"]
    return success_object(serialize(unit), 201)


@bp.get("/stairlift-ops/equipment-units")
def list_equipment_units():
    require_role(*READ_ROLES)
    limit, offset = get_pagination()
    model_code = request.args.get("model_code")
    status = request.args.get("status")
    grade = request.args.get("condition_grade")
    items = sorted(db.equipment_units.values(), key=lambda u: u["created_at"])
    if model_code:
        items = [u for u in items if u["model_code"] == model_code]
    if status:
        items = [u for u in items if u["status"] == status]
    if grade:
        items = [u for u in items if u["condition_grade"] == grade]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(u) for u in page], limit, offset, total)


@bp.get("/stairlift-ops/equipment-units/<uid>")
def get_equipment_unit(uid):
    require_role(*READ_ROLES)
    u = db.equipment_units.get(uid)
    if u is None:
        raise err_not_found("EquipmentUnit not found")
    return success_object(serialize(u))


@bp.post("/stairlift-ops/equipment-units/<uid>/restock")
def restock_equipment_unit(uid):
    user_id, role = require_role("InventoryManager")
    u = db.equipment_units.get(uid)
    if u is None:
        raise err_not_found("EquipmentUnit not found")
    if u["status"] != "REMOVED":
        raise err_invalid_state("EquipmentUnit must be REMOVED to restock")
    if u["condition_grade"] not in ("REFURB_A", "REFURB_B"):
        raise err_invalid_state(
            "Only REFURB_A or REFURB_B units may be restocked")
    u["status"] = "IN_STOCK"
    touch(u)
    audit("EquipmentUnit", u["id"], "UNIT_RESTOCKED", role, {"to": "IN_STOCK"})
    return success_object(serialize(u))


@bp.post("/stairlift-ops/equipment-units/<uid>/retire")
def retire_equipment_unit(uid):
    user_id, role = require_role("InventoryManager")
    u = db.equipment_units.get(uid)
    if u is None:
        raise err_not_found("EquipmentUnit not found")
    if u["status"] != "REMOVED":
        raise err_invalid_state("EquipmentUnit must be REMOVED to retire")
    if u["condition_grade"] not in ("REFURB_C", "RETIRED"):
        raise err_invalid_state(
            "Only REFURB_C or RETIRED units may be retired")
    u["status"] = "RETIRED"
    touch(u)
    audit("EquipmentUnit", u["id"], "UNIT_RETIRED", role, {"to": "RETIRED"})
    return success_object(serialize(u))


@bp.get("/stairlift-ops/equipment-units/<uid>/agreements")
def list_unit_agreements(uid):
    require_role("PlatformAdmin", "InventoryManager", "InstallCoordinator")
    if uid not in db.equipment_units:
        raise err_not_found("EquipmentUnit not found")
    limit, offset = get_pagination()
    items = sorted(
        (a for a in db.agreements.values() if a.get("equipment_unit_id") == uid),
        key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize(a) for a in page], limit, offset, total)
