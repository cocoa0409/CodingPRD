"""Vehicle endpoints (PRD §3.2) including reminder reads and reverse work-order lookup."""
from flask import Blueprint, request

import db
from auth import require_role
from common import (get_json_or_400, require_str, optional_str, require_int,
                    parse_pagination, paginate, sort_by_created, stamp_create, new_id)
from errors import ApiError, ERR_DUPLICATE_VIN, ERR_FORBIDDEN
from response import success_object, success_array
from services import lookup
from services.serialize import vehicle_out, work_order_out

bp = Blueprint("vehicles", __name__)

ALL_ROLES = ("ShopManager", "ServiceAdvisor", "Technician", "FleetManager")
REGISTER_ROLES = ("ShopManager", "ServiceAdvisor", "FleetManager")


@bp.route("/vehicles", methods=["POST"])
def create_vehicle():
    role, uid = require_role(*REGISTER_ROLES)
    body = get_json_or_400()
    shop_id = require_str(body, "shop_id")
    fleet_account_id = optional_str(body, "fleet_account_id", None)
    vin = require_str(body, "vin")
    plate = require_str(body, "plate")
    make = require_str(body, "make")
    model = require_str(body, "model")
    odometer = require_int(body, "odometer", minimum=0)
    lookup.get_shop(shop_id)
    if fleet_account_id is not None:
        lookup.get_fleet_account(fleet_account_id)
        # A FleetManager may only attach a vehicle to its own account.
        if role == "FleetManager" and uid != fleet_account_id:
            raise ApiError(ERR_FORBIDDEN, 403,
                           "fleet manager may only register on its own account")
    elif role == "FleetManager":
        # A FleetManager must scope its registration to its own account.
        raise ApiError(ERR_FORBIDDEN, 403,
                       "fleet manager must attach the vehicle to its own account")
    # Unique VIN among vehicles of the same shop.
    for v in db.vehicles.values():
        if v["shop_id"] == shop_id and v["vin"] == vin:
            raise ApiError(ERR_DUPLICATE_VIN, 409, "vin already exists for this shop")
    vehicle = {
        "id": new_id(),
        "shop_id": shop_id,
        "fleet_account_id": fleet_account_id,
        "vin": vin,
        "plate": plate,
        "make": make,
        "model": model,
        "odometer": odometer,
        "last_service_odometer": None,
        "last_service_date": None,
        "next_service_odometer": None,
        "next_service_date": None,
    }
    stamp_create(vehicle)
    db.vehicles[vehicle["id"]] = vehicle
    return success_object(vehicle_out(vehicle), 201)


@bp.route("/vehicles", methods=["GET"])
def list_vehicles():
    role, uid = require_role(*ALL_ROLES)
    limit, offset = parse_pagination()
    rows = list(db.vehicles.values())
    if role == "FleetManager":
        rows = [v for v in rows if v.get("fleet_account_id") == uid]
    for field in ("shop_id", "fleet_account_id", "vin", "plate"):
        val = request.args.get(field)
        if val is not None:
            rows = [v for v in rows if v.get(field) == val]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([vehicle_out(v) for v in page], limit, offset, total)


@bp.route("/vehicles/<veh_id>", methods=["GET"])
def get_vehicle(veh_id):
    role, uid = require_role(*ALL_ROLES)
    vehicle = lookup.get_vehicle(veh_id)
    if role == "FleetManager" and vehicle.get("fleet_account_id") != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "fleet manager may only read its own vehicles")
    return success_object(vehicle_out(vehicle), 200)


@bp.route("/vehicles/<veh_id>/work-orders", methods=["GET"])
def list_vehicle_work_orders(veh_id):
    role, uid = require_role(*ALL_ROLES)
    vehicle = lookup.get_vehicle(veh_id)
    if role == "FleetManager" and vehicle.get("fleet_account_id") != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "fleet manager may only read its own data")
    limit, offset = parse_pagination()
    rows = [w for w in db.work_orders.values() if w["vehicle_id"] == veh_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return success_array([work_order_out(w) for w in page], limit, offset, total)
