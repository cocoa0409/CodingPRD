from flask import Blueprint, request

import store
from store import DB
from core import (ApiError, get_auth, require_role, get_body, require_fields,
                  check_enum, as_number, as_bool, ok, ok_list, paginate,
                  sorted_records, base_record, touch, g1)
from serializers import ser_truck, ser_compartment
from domain import get_truck, get_compartment_of_truck

bp = Blueprint("trucks", __name__)


@bp.post("/trucks")
def create_truck():
    uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["plate", "home_zone"])
    check_enum(body["home_zone"], store.ZONES, "home_zone")
    rec = base_record()
    rec.update({"plate": body["plate"], "home_zone": body["home_zone"], "status": "AVAILABLE"})
    DB.trucks[rec["id"]] = rec
    return ok(ser_truck(rec), status=201)


@bp.get("/trucks")
def list_trucks():
    uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Driver"})
    items = sorted_records(DB.trucks)
    st = request.args.get("status")
    hz = request.args.get("home_zone")
    if st:
        items = [t for t in items if t["status"] == st]
    if hz:
        items = [t for t in items if t["home_zone"] == hz]
    page, total, limit, offset = paginate(items)
    return ok_list([ser_truck(t) for t in page], total, limit, offset)


@bp.get("/trucks/<tid>")
def get_truck_ep(tid):
    uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Driver"})
    t = get_truck(tid)
    return ok(ser_truck(t))


@bp.post("/trucks/<tid>/maintenance")
def toggle_maintenance(tid):
    uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    t = get_truck(tid)
    body = get_body()
    require_fields(body, ["in_maintenance"])
    in_maint = as_bool(body["in_maintenance"], "in_maintenance")
    if in_maint:
        if t["status"] != "AVAILABLE":
            raise ApiError("ERR_TRUCK_UNAVAILABLE", "Truck not AVAILABLE")
        t["status"] = "MAINTENANCE"
    else:
        if t["status"] != "MAINTENANCE":
            raise ApiError("ERR_TRUCK_UNAVAILABLE", "Truck not in MAINTENANCE")
        t["status"] = "AVAILABLE"
    touch(t)
    return ok(ser_truck(t))


@bp.post("/trucks/<tid>/compartments")
def add_compartment(tid):
    uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    t = get_truck(tid)
    body = get_body()
    require_fields(body, ["fuel_type", "gallons_capacity"])
    check_enum(body["fuel_type"], store.FUEL_TYPES, "fuel_type")
    as_number(body["gallons_capacity"], "gallons_capacity", gt=0)
    onboard = 0
    if "gallons_onboard" in body and body["gallons_onboard"] is not None:
        as_number(body["gallons_onboard"], "gallons_onboard", ge=0)
        onboard = body["gallons_onboard"]
    rec = base_record()
    rec.update({
        "truck_id": tid,
        "fuel_type": body["fuel_type"],
        "gallons_capacity": body["gallons_capacity"],
        "gallons_onboard": onboard,
        "gallons_reserved": 0,
    })
    DB.compartments[rec["id"]] = rec
    return ok(ser_compartment(rec), status=201)


@bp.get("/trucks/<tid>/compartments")
def list_compartments(tid):
    uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Dispatcher", "Driver"})
    get_truck(tid)
    items = [c for c in sorted_records(DB.compartments) if c["truck_id"] == tid]
    page, total, limit, offset = paginate(items)
    return ok_list([ser_compartment(c) for c in page], total, limit, offset)


@bp.post("/trucks/<tid>/restock")
def restock(tid):
    uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    t = get_truck(tid)
    body = get_body()
    require_fields(body, ["compartment_id", "gallons"])
    as_number(body["gallons"], "gallons", gt=0)
    comp = get_compartment_of_truck(tid, body["compartment_id"])
    new_onboard = g1(comp["gallons_onboard"] + body["gallons"])
    if new_onboard > g1(comp["gallons_capacity"]) + 1e-9:
        raise ApiError("ERR_COMPARTMENT_OVERFILL", "Restock exceeds compartment capacity")
    comp["gallons_onboard"] = new_onboard
    touch(comp)
    return ok(ser_compartment(comp))
