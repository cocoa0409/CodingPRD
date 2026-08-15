"""SpareUnit endpoints."""
from flask import Blueprint, request

import db
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from errors import err_state_transition, err_active_reservations
from services.common import (
    body, require_string, require_number, require_enum, parse_pagination,
    paginate, get_spare_unit,
)

bp = Blueprint("spare_units", __name__)

UNIT_TYPES = {"SPARE_TRANSFORMER", "MOBILE_SUBSTATION"}


def spare_unit_view(u):
    return {
        "id": u["id"],
        "unit_type": u["unit_type"],
        "rating_mva": u["rating_mva"],
        "voltage_class_kv": u["voltage_class_kv"],
        "impedance_pct": u["impedance_pct"],
        "home_location": u["home_location"],
        "status": u["status"],
        "created_at": u["created_at"],
        "updated_at": u["updated_at"],
        "version": u["version"],
    }


@bp.post("/spare-units")
def create_spare_unit():
    actor = get_actor()
    require_roles(actor, ["OperationsManager"])
    payload = body()
    unit_type = require_enum(payload, "unit_type", UNIT_TYPES)
    rating_mva = require_number(payload, "rating_mva")
    voltage_class_kv = require_number(payload, "voltage_class_kv")
    impedance_pct = require_number(payload, "impedance_pct")
    home_location = require_string(payload, "home_location")

    ent = {
        "id": db.new_id(),
        "unit_type": unit_type,
        "rating_mva": rating_mva,
        "voltage_class_kv": voltage_class_kv,
        "impedance_pct": impedance_pct,
        "home_location": home_location,
        "status": "AVAILABLE",
    }
    db.stamp_new(ent)
    db.spare_units[ent["id"]] = ent
    return success_object(spare_unit_view(ent), status=201)


@bp.get("/spare-units")
def list_spare_units():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.spare_units.values())
    unit_type = request.args.get("unit_type")
    if unit_type:
        items = [u for u in items if u["unit_type"] == unit_type]
    status = request.args.get("status")
    if status:
        items = [u for u in items if u["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([spare_unit_view(u) for u in page], limit, offset, total)


@bp.get("/spare-units/<id>")
def get_spare_unit_route(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    u = get_spare_unit(id)
    return success_object(spare_unit_view(u))


@bp.post("/spare-units/<id>/decommission")
def decommission_spare_unit(id):
    actor = get_actor()
    require_roles(actor, ["OperationsManager"])
    u = get_spare_unit(id)
    if u["status"] != "AVAILABLE":
        raise err_state_transition("Spare unit is not AVAILABLE")
    # Check no ACTIVE reservations
    for r in db.spare_reservations.values():
        if r["spare_unit_id"] == id and r["status"] == "ACTIVE":
            raise err_active_reservations()
    u["status"] = "DECOMMISSIONED"
    db.touch(u)
    return success_object(spare_unit_view(u))


@bp.get("/spare-units/<id>/reservations")
def list_spare_unit_reservations(id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    u = get_spare_unit(id)
    limit, offset = parse_pagination()
    items = [r for r in db.spare_reservations.values() if r["spare_unit_id"] == id]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    page, total = paginate(items, limit, offset)
    from routes.spare_reservations import spare_reservation_view
    return success_list([spare_reservation_view(r) for r in page], limit, offset, total)
