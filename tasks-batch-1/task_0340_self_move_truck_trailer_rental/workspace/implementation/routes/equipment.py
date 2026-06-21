"""Equipment unit endpoints: create, fetch, list, maintenance/clear/retire."""
from flask import Blueprint, request

import db
import lookup
import validate as V
from errors import err
from middleware import authenticate, require_role
from response import success, list_success
from serialize import public, public_list
from services import domain

bp = Blueprint("equipment", __name__)

FM_LA = {"FleetManager", "LocationAgent"}


@bp.route("/rental/equipment", methods=["POST"])
def create_equipment():
    _, role = authenticate()
    require_role(role, {"FleetManager"})
    body = V.get_json()
    V.require_fields(body, ["equipment_class_id", "home_location_id"])
    class_id = body["equipment_class_id"]
    home_id = body["home_location_id"]
    lookup.require_class(class_id)
    lookup.require_location(home_id)

    odometer = 0
    if body.get("odometer_miles") is not None:
        odometer = V.require_int(body, "odometer_miles", minimum=0)
    fuel = 8
    if body.get("fuel_level_eighths") is not None:
        fuel = V.require_int(body, "fuel_level_eighths", minimum=0)
        if fuel > 8:
            raise err("ERR_INVALID_REQUEST", "fuel_level_eighths must be 0..8.")

    row = db.make_common(db.equipment)
    row.update({
        "equipment_class_id": class_id,
        "home_location_id": home_id,
        "current_location_id": home_id,
        "status": "AVAILABLE",
        "odometer_miles": odometer,
        "fuel_level_eighths": fuel,
    })
    db.equipment.put(row)
    domain.recompute_on_lot_count(home_id)
    return success(public(row), status=201)


@bp.route("/rental/equipment/<rid>", methods=["GET"])
def get_equipment(rid):
    _, role = authenticate()
    require_role(role, FM_LA)
    return success(public(lookup.require_equipment(rid)))


@bp.route("/rental/equipment", methods=["GET"])
def list_equipment():
    _, role = authenticate()
    require_role(role, FM_LA)
    limit, offset = V.parse_pagination()
    rows = db.equipment.all()
    for field in ("equipment_class_id", "current_location_id", "home_location_id", "status"):
        val = request.args.get(field)
        if val:
            rows = [r for r in rows if r.get(field) == val]
    page, total = V.paginate(rows, limit, offset)
    return list_success(public_list(page), limit, offset, total)


@bp.route("/rental/equipment/<rid>/maintenance", methods=["POST"])
def to_maintenance(rid):
    _, role = authenticate()
    require_role(role, {"FleetManager"})
    eq = lookup.require_equipment(rid)
    if eq["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Equipment must be AVAILABLE to enter MAINTENANCE.")
    eq["status"] = "MAINTENANCE"
    db.touch(eq)
    # status stays in on-lot set; count unchanged but recompute for safety.
    domain.recompute_on_lot_count(eq["current_location_id"])
    return success(public(eq))


@bp.route("/rental/equipment/<rid>/clear-maintenance", methods=["POST"])
def clear_maintenance(rid):
    _, role = authenticate()
    require_role(role, {"FleetManager"})
    eq = lookup.require_equipment(rid)
    if eq["status"] != "MAINTENANCE":
        raise err("ERR_INVALID_STATE", "Equipment must be in MAINTENANCE.")
    eq["status"] = "AVAILABLE"
    db.touch(eq)
    domain.recompute_on_lot_count(eq["current_location_id"])
    return success(public(eq))


@bp.route("/rental/equipment/<rid>/retire", methods=["POST"])
def retire(rid):
    _, role = authenticate()
    require_role(role, {"FleetManager"})
    eq = lookup.require_equipment(rid)
    if eq["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Equipment must be AVAILABLE to retire.")
    loc_id = eq["current_location_id"]
    eq["status"] = "RETIRED"
    db.touch(eq)
    domain.recompute_on_lot_count(loc_id)
    return success(public(eq))
