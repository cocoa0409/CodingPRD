"""Vehicle blocks: scheduling, opening, closing and the cancellation cascade."""
from flask import Blueprint

import calculations as calc
import clock
import db
import listing
import response
import serializers
import validation
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from services import blocks as block_service
from services import cascades, metrics

bp = Blueprint("blocks", __name__)

BLOCK_TYPES = ("BASE", "SURGE")
CONFIGURABLE_ZONE_STATES = ("DRAFT", "ACTIVE")


def get_block(block_id):
    block = db.vehicle_blocks.get(block_id)
    if block is None:
        raise ApiError("ERR_VEHICLE_BLOCK_NOT_FOUND")
    return block


@bp.post("/vehicle-blocks")
@endpoint(["ZoneAdmin", "Dispatcher"])
def create_block():
    body = validation.get_body()

    # priority 5 -- body reference existence, in declared input order
    zone_raw = validation.raw_fk(body, "zone_id")
    zone = db.service_zones.get(zone_raw) if zone_raw is not None else None
    if zone_raw is not None and zone is None:
        raise ApiError("ERR_SERVICE_ZONE_NOT_FOUND")
    vehicle_raw = validation.raw_fk(body, "vehicle_id")
    vehicle = db.vehicles.get(vehicle_raw) if vehicle_raw is not None else None
    if vehicle_raw is not None and vehicle is None:
        raise ApiError("ERR_VEHICLE_NOT_FOUND")
    driver_raw = validation.raw_fk(body, "driver_id")
    driver = db.drivers.get(driver_raw) if driver_raw is not None else None
    if driver_raw is not None and driver is None:
        raise ApiError("ERR_DRIVER_NOT_FOUND")

    # priority 7 -- request shape
    validation.req_str(body, "zone_id")
    validation.req_str(body, "vehicle_id")
    validation.req_str(body, "driver_id")
    block_type = validation.req_enum(body, "block_type", BLOCK_TYPES)
    start_raw, start_dt = validation.req_datetime(body, "start_utc")
    end_raw, end_dt = validation.req_datetime(body, "end_utc")
    if end_dt <= start_dt:
        validation.invalid("end_utc must be later than start_utc.")

    # priority 13 -- zone must be DRAFT or ACTIVE
    if zone["status"] not in CONFIGURABLE_ZONE_STATES:
        raise ApiError("ERR_ZONE_NOT_ACTIVE")

    # priority 15 -- cross-zone consistency
    if vehicle["zone_id"] != zone["id"] or driver["zone_id"] != zone["id"]:
        raise ApiError("ERR_ZONE_MISMATCH")

    # priority 22 / 23 -- the two temporal exclusions
    if block_service.vehicle_occupied(vehicle["id"], start_dt, end_dt):
        raise ApiError("ERR_VEHICLE_BLOCK_OVERLAP")
    if block_service.driver_rest_violated(driver["id"], start_dt, end_dt):
        raise ApiError("ERR_DRIVER_REST_BUFFER")

    block = db.base_record()
    block.update({
        "zone_id": zone["id"],
        "vehicle_id": vehicle["id"],
        "driver_id": driver["id"],
        "block_type": block_type,
        "start_utc": start_raw,
        "end_utc": end_raw,
        "state": "SCHEDULED",
        "opened_at": None,
        "closed_at": None,
        "seats_committed": 0,
        "wav_positions_committed": 0,
        "committed_index_min": None,
        "committed_index_max": None,
        "boardings_count": 0,
        "scheduled_revenue_hours": calc.hours_between_2dp(end_dt, start_dt),
        "actual_revenue_hours": 0.00,
    })
    db.vehicle_blocks.add(block)
    return response.created(serializers.pick(block, serializers.VEHICLE_BLOCK))


@bp.post("/vehicle-blocks/<block_id>/open")
@endpoint(["Dispatcher"])
def open_block(block_id):
    block = get_block(block_id)
    if block["state"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_BLOCK_STATE")
    zone = db.service_zones.get(block["zone_id"])
    if zone is None or zone["status"] != "ACTIVE":
        raise ApiError("ERR_ZONE_NOT_ACTIVE")
    vehicle = db.vehicles.get(block["vehicle_id"])
    if vehicle is None or vehicle["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_VEHICLE_STATE")
    driver = db.drivers.get(block["driver_id"])
    if driver is None or driver["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_DRIVER_STATE")
    if block_service.fleet_size_exceeded(block):
        raise ApiError("ERR_FLEET_SIZE_EXCEEDED")

    block["state"] = "OPEN"
    block["opened_at"] = clock.now_raw()
    db.touch(block)
    return response.object_response(
        serializers.pick(block, serializers.VEHICLE_BLOCK))


@bp.post("/vehicle-blocks/<block_id>/close")
@endpoint(["Dispatcher"])
def close_block(block_id):
    block = get_block(block_id)
    if block["state"] != "OPEN":
        raise ApiError("ERR_INVALID_BLOCK_STATE")
    if block_service.active_assignments(block["id"]):
        raise ApiError("ERR_BLOCK_HAS_ACTIVE_ASSIGNMENTS")

    block["state"] = "CLOSED"
    block["closed_at"] = clock.now_raw()
    opened_dt = clock.parse_dt(block["opened_at"])
    closed_dt = clock.parse_dt(block["closed_at"])
    if opened_dt is not None and closed_dt is not None:
        block["actual_revenue_hours"] = calc.hours_between_2dp(closed_dt, opened_dt)
    db.touch(block)

    metrics.recompute_zone_by_id(block["zone_id"])
    return response.object_response(
        serializers.pick(block, serializers.VEHICLE_BLOCK))


@bp.post("/vehicle-blocks/<block_id>/cancel")
@endpoint(["Dispatcher"])
def cancel_block(block_id):
    block = get_block(block_id)
    body = validation.get_body()
    validation.opt_str(body, "note", min_len=0)

    if block["state"] not in ("SCHEDULED", "OPEN"):
        raise ApiError("ERR_INVALID_BLOCK_STATE")
    for assignment in block_service.assignments_of(block["id"]):
        if assignment["state"] == "ONBOARD":
            raise ApiError("ERR_BLOCK_HAS_ACTIVE_ASSIGNMENTS")

    cascades.cancel_open_block(block)
    return response.object_response(
        serializers.pick(block, serializers.VEHICLE_BLOCK))


@bp.get("/vehicle-blocks/<block_id>")
@endpoint(ALL_ROLES)
def read_block(block_id):
    block = get_block(block_id)
    return response.object_response(
        serializers.pick(block, serializers.VEHICLE_BLOCK))


@bp.get("/vehicle-blocks")
@endpoint(ALL_ROLES)
def list_blocks():
    return listing.list_endpoint(
        db.vehicle_blocks.ordered(), serializers.VEHICLE_BLOCK,
        {"zone_id": "zone_id", "vehicle_id": "vehicle_id",
         "driver_id": "driver_id", "state": "state", "block_type": "block_type"})
