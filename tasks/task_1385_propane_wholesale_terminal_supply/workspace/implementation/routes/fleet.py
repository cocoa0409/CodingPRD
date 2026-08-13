"""Freight zone + transport truck endpoints."""
from flask import Blueprint

import db
import middleware as mw
import response as resp
import serializers as ser
import services as svc
from errors import (
    err_not_found,
    err_referenced_not_found,
    err_invalid_request,
    err_invalid_state,
    err_duplicate_zone_code,
    err_duplicate_truck_unit,
)

bp = Blueprint("fleet", __name__)

ZONE_READ_ROLES = ["SupplyAdmin", "SupplyPlanner", "Dispatcher", "CreditManager", "DealerUser"]
TRUCK_READ_ROLES = ["SupplyAdmin", "SupplyPlanner", "Dispatcher"]
TRUCK_TRANSITION_ROLES = ["SupplyAdmin", "Dispatcher"]
TRUCK_STATES = {"AVAILABLE", "OUT_OF_SERVICE"}


# ---------------------------------------------------------------------------
# Freight zones
# ---------------------------------------------------------------------------

@bp.route("/freight-zones", methods=["POST"])
def create_freight_zone():
    caller = mw.authenticate()
    mw.authorize(caller, ["SupplyAdmin"])
    body = mw.get_json_body(required=True)
    terminal_id = mw.req_string(body, "terminal_id")
    zone_code = mw.req_string(body, "zone_code")
    one_way_drive_minutes = mw.req_int(body, "one_way_drive_minutes")
    freight_mc_per_gal = mw.req_int(body, "freight_mc_per_gal")
    min_freight_cents = mw.req_int(body, "min_freight_cents")

    if terminal_id not in db.terminals:
        raise err_referenced_not_found("terminal_id does not resolve")

    if one_way_drive_minutes <= 0 or freight_mc_per_gal < 0 or min_freight_cents < 0:
        raise err_invalid_request("zone numeric field out of range")

    for z in db.freight_zones.values():
        if z["terminal_id"] == terminal_id and z["zone_code"] == zone_code:
            raise err_duplicate_zone_code()

    now = svc.stamp_now()
    z = {
        "id": db.new_id(),
        "terminal_id": terminal_id,
        "zone_code": zone_code,
        "one_way_drive_minutes": one_way_drive_minutes,
        "freight_mc_per_gal": freight_mc_per_gal,
        "min_freight_cents": min_freight_cents,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.freight_zones[z["id"]] = z
    return resp.created(ser.serialize_freight_zone(z))


@bp.route("/freight-zones/<zid>", methods=["GET"])
def get_freight_zone(zid):
    caller = mw.authenticate()
    mw.authorize(caller, ZONE_READ_ROLES)
    z = db.freight_zones.get(zid)
    if z is None:
        raise err_not_found()
    return resp.ok(ser.serialize_freight_zone(z))


@bp.route("/freight-zones", methods=["GET"])
def list_freight_zones():
    caller = mw.authenticate()
    mw.authorize(caller, ZONE_READ_ROLES)
    limit, offset = mw.pagination_params()
    terminal_id = mw.opt_query_string("terminal_id")
    items = list(db.freight_zones.values())
    if terminal_id is not None:
        items = [z for z in items if z["terminal_id"] == terminal_id]
    items.sort(key=lambda z: z["_seq"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.list_ok([ser.serialize_freight_zone(z) for z in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Trucks
# ---------------------------------------------------------------------------

@bp.route("/trucks", methods=["POST"])
def create_truck():
    caller = mw.authenticate()
    mw.authorize(caller, ["SupplyAdmin"])
    body = mw.get_json_body(required=True)
    terminal_id = mw.req_string(body, "terminal_id")
    unit_number = mw.req_string(body, "unit_number")
    capacity_gal = mw.req_int(body, "capacity_gal")
    weekly_hours_limit_minutes = mw.req_int(body, "weekly_hours_limit_minutes")

    if terminal_id not in db.terminals:
        raise err_referenced_not_found("terminal_id does not resolve")

    if capacity_gal <= 0 or weekly_hours_limit_minutes <= 0:
        raise err_invalid_request("truck numeric field out of range")

    for t in db.trucks.values():
        if t["terminal_id"] == terminal_id and t["unit_number"] == unit_number:
            raise err_duplicate_truck_unit()

    now = svc.stamp_now()
    t = {
        "id": db.new_id(),
        "terminal_id": terminal_id,
        "unit_number": unit_number,
        "capacity_gal": capacity_gal,
        "weekly_hours_limit_minutes": weekly_hours_limit_minutes,
        "status": "AVAILABLE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.trucks[t["id"]] = t
    return resp.created(ser.serialize_truck(t))


@bp.route("/trucks/<tid>", methods=["GET"])
def get_truck(tid):
    caller = mw.authenticate()
    mw.authorize(caller, TRUCK_READ_ROLES)
    t = db.trucks.get(tid)
    if t is None:
        raise err_not_found()
    return resp.ok(ser.serialize_truck(t))


@bp.route("/trucks", methods=["GET"])
def list_trucks():
    caller = mw.authenticate()
    mw.authorize(caller, TRUCK_READ_ROLES)
    limit, offset = mw.pagination_params()
    terminal_id = mw.opt_query_string("terminal_id")
    status = mw.opt_query_enum("status", TRUCK_STATES)
    items = list(db.trucks.values())
    if terminal_id is not None:
        items = [t for t in items if t["terminal_id"] == terminal_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items.sort(key=lambda t: t["_seq"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.list_ok([ser.serialize_truck(t) for t in page], limit, offset, total)


@bp.route("/trucks/<tid>/transition", methods=["POST"])
def transition_truck(tid):
    caller = mw.authenticate()
    mw.authorize(caller, TRUCK_TRANSITION_ROLES)
    t = db.trucks.get(tid)
    if t is None:
        raise err_not_found()
    body = mw.get_json_body(required=True)
    to_state = mw.req_enum(body, "to_state", TRUCK_STATES)
    if to_state == t["status"]:
        raise err_invalid_state(f"Truck is already {to_state}")
    t["status"] = to_state
    svc.touch(t)
    if to_state == "OUT_OF_SERVICE":
        for o in db.delivery_orders.values():
            if o["truck_id"] == t["id"] and o["fulfillment_status"] == "SCHEDULED":
                svc.unschedule_order(o)
                svc.touch(o)
    return resp.ok(ser.serialize_truck(t))
