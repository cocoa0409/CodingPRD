"""Inventory unit endpoints."""
from flask import Blueprint, request

from core import (
    db, ApiError, body, ok_object, paginate, new_record, touch, serialize,
    require_roles, get_unit_or_404, req_str, req_enum, req_int, opt_enum,
)

bp = Blueprint("inventory", __name__)

RAMP_TYPES = ("MODULAR_ALUMINUM", "PORTABLE_THRESHOLD", "SUITCASE", "CUSTOM_WOOD")
CONDITION_GRADES = ("A", "B", "C", "D")


@bp.route("/inventory-units", methods=["POST"])
def create_unit():
    require_roles("LogisticsCoordinator")
    b = body()
    rec = new_record()
    rec.update({
        "unit_tag": req_str(b, "unit_tag"),
        "ramp_type": req_enum(b, "ramp_type", RAMP_TYPES),
        "length_feet": req_int(b, "length_feet"),
        "width_inches": req_int(b, "width_inches"),
        "weight_capacity_lbs": req_int(b, "weight_capacity_lbs"),
        "status": "AVAILABLE",
        "condition_grade": opt_enum(b, "condition_grade", CONDITION_GRADES, "A"),
        "monthly_rate_cents": req_int(b, "monthly_rate_cents"),
        "purchase_price_cents": req_int(b, "purchase_price_cents"),
        "current_case_id": None,
        "total_rental_days": 0,
    })
    db["inventory_units"][rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/inventory-units", methods=["GET"])
def list_units():
    require_roles()
    status = request.args.get("status")
    ramp_type = request.args.get("ramp_type")
    records = list(db["inventory_units"].values())
    if status is not None:
        records = [u for u in records if u["status"] == status]
    if ramp_type is not None:
        records = [u for u in records if u["ramp_type"] == ramp_type]
    return paginate(records)


@bp.route("/inventory-units/<unitId>", methods=["GET"])
def get_unit(unitId):
    require_roles()
    return ok_object(serialize(get_unit_or_404(unitId)))


@bp.route("/inventory-units/<unitId>/maintenance", methods=["POST"])
def maintenance(unitId):
    require_roles("LogisticsCoordinator")
    unit = get_unit_or_404(unitId)
    if unit["status"] not in ("AVAILABLE", "DEPLOYED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Unit must be AVAILABLE or DEPLOYED to enter maintenance")
    unit["status"] = "MAINTENANCE"
    touch(unit)
    return ok_object(serialize(unit))


@bp.route("/inventory-units/<unitId>/return-to-service", methods=["POST"])
def return_to_service(unitId):
    require_roles("LogisticsCoordinator")
    unit = get_unit_or_404(unitId)
    if unit["status"] != "MAINTENANCE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Unit must be MAINTENANCE to return to service")
    unit["status"] = "AVAILABLE"
    touch(unit)
    return ok_object(serialize(unit))


@bp.route("/inventory-units/<unitId>/retire", methods=["POST"])
def retire(unitId):
    require_roles("LogisticsCoordinator")
    unit = get_unit_or_404(unitId)
    if unit["status"] not in ("AVAILABLE", "MAINTENANCE"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Unit must be AVAILABLE or MAINTENANCE to retire")
    unit["status"] = "RETIRED"
    touch(unit)
    return ok_object(serialize(unit))
