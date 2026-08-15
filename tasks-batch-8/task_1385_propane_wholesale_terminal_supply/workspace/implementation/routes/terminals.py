"""Terminal endpoints."""
from flask import Blueprint

import db
import middleware as mw
import response as resp
import serializers as ser
import services as svc
from errors import err_not_found, err_invalid_request

bp = Blueprint("terminals", __name__)

READ_ROLES = ["SupplyAdmin", "SupplyPlanner", "Dispatcher", "CreditManager", "SystemAdmin"]


@bp.route("/terminals", methods=["POST"])
def create_terminal():
    caller = mw.authenticate()
    mw.authorize(caller, ["SupplyAdmin"])
    body = mw.get_json_body(required=True)
    name = mw.req_string(body, "name")
    region_code = mw.req_string(body, "region_code")
    storage_capacity_gal = mw.req_int(body, "storage_capacity_gal")
    reserve_floor_gal = mw.req_int(body, "reserve_floor_gal")
    winter_reserve_floor_gal = mw.req_int(body, "winter_reserve_floor_gal")
    rack_bay_count = mw.req_int(body, "rack_bay_count")

    if storage_capacity_gal <= 0 or reserve_floor_gal < 0 or rack_bay_count < 1:
        raise err_invalid_request("Field value out of range")
    if winter_reserve_floor_gal < reserve_floor_gal:
        raise err_invalid_request("winter_reserve_floor_gal must be >= reserve_floor_gal")

    now = svc.stamp_now()
    t = {
        "id": db.new_id(),
        "name": name,
        "region_code": region_code,
        "storage_capacity_gal": storage_capacity_gal,
        "reserve_floor_gal": reserve_floor_gal,
        "winter_reserve_floor_gal": winter_reserve_floor_gal,
        "rack_bay_count": rack_bay_count,
        "on_hand_gal": 0,
        "allocation_posture": "NORMAL",
        "ops_epoch": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.terminals[t["id"]] = t
    return resp.created(ser.serialize_terminal(t))


@bp.route("/terminals/<tid>", methods=["GET"])
def get_terminal(tid):
    caller = mw.authenticate()
    mw.authorize(caller, READ_ROLES)
    t = db.terminals.get(tid)
    if t is None:
        raise err_not_found()
    return resp.ok(ser.serialize_terminal(t))


@bp.route("/terminals/<tid>/inventory-summary", methods=["GET"])
def inventory_summary(tid):
    caller = mw.authenticate()
    mw.authorize(caller, READ_ROLES)
    t = db.terminals.get(tid)
    if t is None:
        raise err_not_found()
    return resp.ok(ser.serialize_inventory_summary(t))
