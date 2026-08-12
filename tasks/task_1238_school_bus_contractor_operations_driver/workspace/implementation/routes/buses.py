"""Bus endpoints."""
from flask import Blueprint, request

import db
from envelope import success_list, success_object
from errors import ERR_ALREADY_TERMINAL, ERR_INVALID_STATE, raise_err
from middleware import authenticate, get_or_404, require_roles
from validation import (
    get_body,
    opt_str,
    paginate,
    pagination_params,
    req_date,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("buses", __name__)

ROLES = {"SystemAdmin", "DistrictAdmin", "ContractorOps", "FleetManager"}


@bp.route("/busops/buses", methods=["POST"])
def create_bus():
    body = get_body()
    district_id = req_str(body, "district_id")
    fleet_number = req_str(body, "fleet_number")
    capacity = req_int(body, "capacity", minimum=0)
    fuel_type = req_enum(body, "fuel_type", ("DIESEL", "GASOLINE", "ELECTRIC"))
    mpg_x10 = req_int(body, "mpg_x10", minimum=1)
    next_inspection_due = req_date(body, "next_inspection_due")
    actor = authenticate()
    require_roles(actor, {"FleetManager"})
    get_or_404("districts", district_id, "District")

    rec = {
        "id": db.new_id(),
        "district_id": district_id,
        "fleet_number": fleet_number,
        "capacity": capacity,
        "fuel_type": fuel_type,
        "mpg_x10": mpg_x10,
        "odometer_miles": 0,
        "status": "IN_SERVICE",
        "next_inspection_due": next_inspection_due,
    }
    db.stamp_new(rec)
    db.STORES["buses"][rec["id"]] = rec
    return success_object(db.public(rec), status=201)


@bp.route("/busops/buses", methods=["GET"])
def list_buses():
    limit, offset = pagination_params()
    actor = authenticate()
    require_roles(actor, ROLES)
    items = list(db.all_of("buses"))
    district_id = request.args.get("district_id")
    status = request.args.get("status")
    if district_id is not None:
        items = [b for b in items if b["district_id"] == district_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, info = paginate(items, limit, offset)
    return success_list(page, info)


@bp.route("/busops/buses/<rid>", methods=["GET"])
def get_bus(rid):
    actor = authenticate()
    require_roles(actor, ROLES)
    rec = get_or_404("buses", rid, "Bus")
    return success_object(db.public(rec))


@bp.route("/busops/buses/<rid>/events", methods=["POST"])
def bus_events(rid):
    body = get_body()
    action = req_enum(body, "action", ("DECOMMISSION",))
    opt_str(body, "reason")
    actor = authenticate()
    require_roles(actor, {"FleetManager"})
    bus = get_or_404("buses", rid, "Bus")

    if bus["status"] == "DECOMMISSIONED":
        raise_err(ERR_ALREADY_TERMINAL, "Bus is DECOMMISSIONED (terminal)")
    if bus["status"] not in ("IN_SERVICE", "IN_SHOP", "GROUNDED"):
        raise_err(ERR_INVALID_STATE, "Bus cannot be decommissioned from %s" % bus["status"])
    today = db.clock_date().isoformat()
    for a in db.all_of("assignments"):
        if a.get("bus_id") != bus["id"]:
            continue
        if a["status"] not in ("PLANNED", "CONFIRMED", "EN_ROUTE"):
            continue
        day = db.day_of_assignment(a)
        if day is not None and day["service_date"] >= today:
            raise_err(
                ERR_INVALID_STATE,
                "Bus has future assignments and cannot be decommissioned",
            )
    bus["status"] = "DECOMMISSIONED"
    db.touch(bus)
    return success_object(db.public(bus))
