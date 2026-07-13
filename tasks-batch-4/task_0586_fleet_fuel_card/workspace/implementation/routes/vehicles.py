"""Vehicles: onboarding, listing, MPG, retirement (PRD §3.1, §3.8)."""
from flask import Blueprint, g, request

import response
from db import base_record, db
from errors import err
from middleware import (body, check_fleet, is_fleet_manager, opt_num, paginate, query_enum,
                        req_num, req_str, require_roles)
from services import serialize
from services.cascade import retire_vehicle
from services.mpg import compute_mpg
from services.store import VEHICLE_STATUSES, get_account, get_vehicle

bp = Blueprint("vehicles", __name__)


@bp.post("/vehicles")
@require_roles("FleetManager")
def create_vehicle():
    data = body()
    fleet_account_id = req_str(data, "fleet_account_id")
    plate = req_str(data, "plate")
    tank = req_num(data, "tank_capacity_gallons", exclusive_min=0)
    mpg_min = req_num(data, "expected_mpg_min", exclusive_min=0)
    mpg_max = req_num(data, "expected_mpg_max", exclusive_min=0)
    if mpg_max < mpg_min:
        raise err("ERR_VALIDATION", "Field 'expected_mpg_max' must be >= 'expected_mpg_min'.")
    home = req_str(data, "home_jurisdiction")
    starting = opt_num(data, "starting_odometer", 0, minimum=0)

    account = get_account(fleet_account_id)
    check_fleet(account["id"])

    record = base_record()
    record.update({
        "fleet_account_id": fleet_account_id,
        "plate": plate,
        "tank_capacity_gallons": tank,
        "starting_odometer": starting,
        "expected_mpg_min": mpg_min,
        "expected_mpg_max": mpg_max,
        "home_jurisdiction": home,
        "status": "ACTIVE",
    })
    db.vehicles[record["id"]] = record
    return response.created(serialize.vehicle(record))


@bp.get("/vehicles/<vehicle_id>")
@require_roles("FleetManager", "ProgramAdmin")
def fetch_vehicle(vehicle_id):
    vehicle = get_vehicle(vehicle_id)
    check_fleet(vehicle["fleet_account_id"])
    return response.ok(serialize.vehicle(vehicle))


@bp.get("/vehicles")
@require_roles("FleetManager", "ProgramAdmin")
def list_vehicles():
    account_filter = request.args.get("fleet_account_id")
    status_filter = query_enum("status", VEHICLE_STATUSES)

    if is_fleet_manager():
        if account_filter is not None and account_filter != g.user_id:
            raise err("ERR_FORBIDDEN_FLEET")
        account_filter = g.user_id

    records = list(db.vehicles.values())
    if account_filter is not None:
        records = [v for v in records if v["fleet_account_id"] == account_filter]
    if status_filter is not None:
        records = [v for v in records if v["status"] == status_filter]

    page, total, limit, offset = paginate(records)
    return response.listing([serialize.vehicle(v) for v in page], limit, offset, total)


@bp.get("/vehicles/<vehicle_id>/mpg")
@require_roles("FleetManager", "ProgramAdmin")
def vehicle_mpg(vehicle_id):
    vehicle = get_vehicle(vehicle_id)
    check_fleet(vehicle["fleet_account_id"])
    method = query_enum("method", ("SEGMENT", "ROLLING")) or "SEGMENT"
    return response.ok(compute_mpg(vehicle, method))


@bp.post("/vehicles/<vehicle_id>/retire")
@require_roles("FleetManager")
def retire(vehicle_id):
    vehicle = get_vehicle(vehicle_id)
    check_fleet(vehicle["fleet_account_id"])
    if vehicle["status"] not in ("ACTIVE", "OUT_OF_SERVICE"):
        raise err("ERR_VEHICLE_OUT_OF_SERVICE", "Vehicle is already RETIRED.")
    retire_vehicle(vehicle)
    return response.ok(serialize.vehicle(vehicle))
