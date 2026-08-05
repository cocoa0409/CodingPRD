from flask import Blueprint, request

import store
from store import DB
from core import (ApiError, get_auth, require_role, get_body, require_fields,
                  check_enum, as_int, as_number, ok, ok_list, paginate,
                  sorted_records, base_record, touch, deny)
from serializers import ser_vehicle
from domain import get_customer, get_fleet_account, get_vehicle

bp = Blueprint("vehicles", __name__)


def suspend_vehicle_effects(v):
    """Apply the ACTIVE -> SUSPENDED cascade (fleet counters + auto-suspend)."""
    v["status"] = "SUSPENDED"
    touch(v)
    if v["fleet_account_id"]:
        f = DB.fleet_accounts.get(v["fleet_account_id"])
        if f:
            f["suspended_vehicle_count"] += 1
            f["active_vehicle_count"] -= 1
            if f["active_vehicle_count"] <= 0 and f["status"] == "ACTIVE":
                f["status"] = "SUSPENDED"
            touch(f)


def reactivate_vehicle_effects(v):
    v["status"] = "ACTIVE"
    touch(v)
    if v["fleet_account_id"]:
        f = DB.fleet_accounts.get(v["fleet_account_id"])
        if f:
            f["suspended_vehicle_count"] -= 1
            f["active_vehicle_count"] += 1
            touch(f)


@bp.post("/vehicles")
def create_vehicle():
    uid, role = get_auth()
    require_role(role, {"Member", "FleetManager"})
    body = get_body()
    require_fields(body, ["customer_id", "make_model", "fuel_type", "tank_capacity_gallons"])
    check_enum(body["fuel_type"], store.FUEL_TYPES, "fuel_type")
    as_number(body["tank_capacity_gallons"], "tank_capacity_gallons", gt=0)
    fuel_level = 0
    if "current_fuel_level_gallons" in body and body["current_fuel_level_gallons"] is not None:
        as_number(body["current_fuel_level_gallons"], "current_fuel_level_gallons", ge=0)
        fuel_level = body["current_fuel_level_gallons"]
    cap = 0
    if "monthly_spend_cap_cents" in body and body["monthly_spend_cap_cents"] is not None:
        cap = as_int(body["monthly_spend_cap_cents"], "monthly_spend_cap_cents", minimum=0)
    fleet_account_id = body.get("fleet_account_id")

    if body["customer_id"] != uid:
        deny()
    get_customer(body["customer_id"])
    fleet = None
    if fleet_account_id is not None:
        fleet = get_fleet_account(fleet_account_id)

    rec = base_record()
    rec.update({
        "customer_id": body["customer_id"],
        "fleet_account_id": fleet_account_id,
        "make_model": body["make_model"],
        "fuel_type": body["fuel_type"],
        "tank_capacity_gallons": body["tank_capacity_gallons"],
        "current_fuel_level_gallons": fuel_level,
        "monthly_spend_cap_cents": cap,
        "committed_spend_cents": 0,
        "settled_spend_cents": 0,
        "status": "ACTIVE",
    })
    DB.vehicles[rec["id"]] = rec
    if fleet is not None:
        fleet["active_vehicle_count"] += 1
        touch(fleet)
    return ok(ser_vehicle(rec), status=201)


@bp.get("/vehicles")
def list_vehicles():
    uid, role = get_auth()
    require_role(role, {"Member", "FleetManager", "Dispatcher", "PlatformAdmin"})
    items = sorted_records(DB.vehicles)
    if role in ("Member", "FleetManager"):
        items = [v for v in items if v["customer_id"] == uid]
    cid = request.args.get("customer_id")
    faid = request.args.get("fleet_account_id")
    st = request.args.get("status")
    if cid:
        items = [v for v in items if v["customer_id"] == cid]
    if faid:
        items = [v for v in items if v["fleet_account_id"] == faid]
    if st:
        items = [v for v in items if v["status"] == st]
    page, total, limit, offset = paginate(items)
    return ok_list([ser_vehicle(v) for v in page], total, limit, offset)


@bp.get("/vehicles/<vid>")
def get_vehicle_ep(vid):
    uid, role = get_auth()
    require_role(role, {"Member", "FleetManager", "Dispatcher", "PlatformAdmin"})
    v = get_vehicle(vid)
    if role in ("Member", "FleetManager") and v["customer_id"] != uid:
        deny()
    return ok(ser_vehicle(v))


@bp.post("/vehicles/<vid>/suspend")
def suspend_vehicle(vid):
    uid, role = get_auth()
    require_role(role, {"FleetManager"})
    v = get_vehicle(vid)
    if v["customer_id"] != uid:
        deny()
    if v["status"] != "ACTIVE":
        raise ApiError("ERR_VEHICLE_SUSPENDED", "Vehicle is not ACTIVE")
    suspend_vehicle_effects(v)
    return ok(ser_vehicle(v))


@bp.post("/vehicles/<vid>/reactivate")
def reactivate_vehicle(vid):
    uid, role = get_auth()
    require_role(role, {"FleetManager"})
    v = get_vehicle(vid)
    if v["customer_id"] != uid:
        deny()
    if v["status"] != "SUSPENDED":
        raise ApiError("ERR_VEHICLE_SUSPENDED", "Vehicle is not SUSPENDED")
    reactivate_vehicle_effects(v)
    return ok(ser_vehicle(v))
