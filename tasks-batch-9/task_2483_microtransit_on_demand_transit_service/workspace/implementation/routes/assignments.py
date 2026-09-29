"""Pool assignments (the driver's manifest) and the immutable fare ledger."""
from flask import Blueprint

import calculations as calc
import clock
import db
import listing
import middleware
import response
import serializers
import validation
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from services import blocks as block_service
from services import cascades, fares, metrics, offers

bp = Blueprint("assignments", __name__)


def get_assignment(assignment_id):
    assignment = db.pool_assignments.get(assignment_id)
    if assignment is None:
        raise ApiError("ERR_POOL_ASSIGNMENT_NOT_FOUND")
    return assignment


def _block_of(assignment):
    return db.vehicle_blocks.get(assignment["block_id"])


def _trip_of(assignment):
    return db.trip_requests.get(assignment["trip_request_id"])


def _require_driver_of(assignment):
    block = _block_of(assignment)
    middleware.require_driver_owner(block["driver_id"] if block else None)
    return block


# --------------------------------------------------------------------------
# manual dispatch
# --------------------------------------------------------------------------

@bp.post("/pool-assignments")
@endpoint(["Dispatcher"])
def create_assignment():
    body = validation.get_body()

    # priority 5 -- body reference existence, in declared input order
    trip_raw = validation.raw_fk(body, "trip_request_id")
    trip = db.trip_requests.get(trip_raw) if trip_raw is not None else None
    if trip_raw is not None and trip is None:
        raise ApiError("ERR_TRIP_REQUEST_NOT_FOUND")
    block_raw = validation.raw_fk(body, "block_id")
    block = db.vehicle_blocks.get(block_raw) if block_raw is not None else None
    if block_raw is not None and block is None:
        raise ApiError("ERR_VEHICLE_BLOCK_NOT_FOUND")

    # priority 7 -- request shape
    validation.req_str(body, "trip_request_id")
    validation.req_str(body, "block_id")
    expected_version = validation.req_int(body, "expected_vehicle_block_version")

    # priority 11 -- declared transition
    if trip["status"] not in ("RECEIVED", "MATCHING"):
        raise ApiError("ERR_INVALID_TRIP_STATE")
    if block["state"] != "OPEN":
        raise ApiError("ERR_INVALID_BLOCK_STATE")

    # priority 12 -- the zone must be ACTIVE for dispatch
    zone = db.service_zones.get(trip["zone_id"])
    if zone is None or zone["status"] != "ACTIVE":
        raise ApiError("ERR_ZONE_NOT_ACTIVE")

    # priority 14 -- stale-view protection on the capacity-bearing parent
    if expected_version != block["version"]:
        raise ApiError("ERR_STALE_VEHICLE_BLOCK_VERSION")

    # priority 15 -- cross-zone consistency
    if trip["zone_id"] != block["zone_id"]:
        raise ApiError("ERR_ZONE_MISMATCH")

    vehicle = db.vehicles.get(block["vehicle_id"])
    driver = db.drivers.get(block["driver_id"])

    # priority 20 -- wheelchair-accessible dispatch capability
    if trip["wav_required"]:
        if vehicle is None or vehicle["wav_positions"] < 1 or driver is None \
                or not driver["wav_certified"]:
            raise ApiError("ERR_WAV_UNAVAILABLE")

    # priority 24 -- the pickup must fall in the block's half-open window
    requested_dt = clock.parse_dt(trip["requested_pickup_utc"])
    start_dt, end_dt = block_service.window(block)
    if not (start_dt <= requested_dt < end_dt):
        raise ApiError("ERR_PICKUP_OUTSIDE_BLOCK_WINDOW")

    # priority 26 -- the quarter-hour curb ceiling at the origin stop
    _pickup_raw, prospective_dt = offers.promised_pickup(trip)
    used = offers.curb_bucket_count(trip["origin_stop_id"], prospective_dt)
    if used >= zone["curb_capacity_per_bucket"]:
        raise ApiError("ERR_CURB_CAPACITY_EXCEEDED")

    # priority 28 -- shared-ride detour tolerance
    baseline, detour = offers.geometry(trip, block)
    if detour > calc.detour_allowance_minutes(zone, baseline):
        raise ApiError("ERR_DETOUR_TOLERANCE_EXCEEDED")

    # priority 32 -- seat capacity
    if block["seats_committed"] + trip["party_size"] > vehicle["seat_capacity"]:
        raise ApiError("ERR_SEAT_CAPACITY_EXCEEDED")

    # priority 33 -- securement-position capacity
    if trip["wav_required"]:
        headroom = vehicle["wav_positions"] - block["wav_positions_committed"]
        if headroom < 1:
            raise ApiError("ERR_WAV_POSITION_UNAVAILABLE")

    assignment = offers.create_offer(trip, block, "MANUAL_DISPATCH", None)
    return response.created(
        serializers.pick(assignment, serializers.POOL_ASSIGNMENT))


# --------------------------------------------------------------------------
# the four driver actions
# --------------------------------------------------------------------------

@bp.post("/pool-assignments/<assignment_id>/accept")
@endpoint(["DriverUser"])
def accept_assignment(assignment_id):
    assignment = get_assignment(assignment_id)
    block = _require_driver_of(assignment)

    if assignment["state"] != "OFFERED":
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE")
    if block is None or block["state"] != "OPEN":
        raise ApiError("ERR_INVALID_BLOCK_STATE")

    assignment["state"] = "ACCEPTED"
    db.touch(assignment)

    trip = _trip_of(assignment)
    if trip is not None:
        trip["status"] = "ASSIGNED"
        db.touch(trip)

    driver = db.drivers.get(block["driver_id"])
    if driver is not None and driver["consecutive_decline_count"] != 0:
        driver["consecutive_decline_count"] = 0
        db.touch(driver)

    block_service.recompute_seq_pickup(block["id"])
    return response.object_response(
        serializers.pick(assignment, serializers.POOL_ASSIGNMENT))


@bp.post("/pool-assignments/<assignment_id>/decline")
@endpoint(["DriverUser"])
def decline_assignment(assignment_id):
    assignment = get_assignment(assignment_id)
    block = _require_driver_of(assignment)
    body = validation.get_body()
    validation.opt_str(body, "reason", min_len=0)

    if assignment["state"] != "OFFERED":
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE")
    if block is None or block["state"] != "OPEN":
        raise ApiError("ERR_INVALID_BLOCK_STATE")

    assignment["state"] = "DECLINED"
    db.touch(assignment)

    # HOP 1 -- the block gets its capacity back
    block_service.recompute_block(block)

    # HOP 2 -- the decline streak grows and the trip is un-booked
    driver = db.drivers.get(block["driver_id"])
    if driver is not None:
        driver["consecutive_decline_count"] += 1
        db.touch(driver)

    trip = _trip_of(assignment)
    if trip is not None:
        cascades.requeue_or_exhaust(trip)

    # HOP 3 -- the roster consequence
    if driver is not None and driver["status"] == "ACTIVE" and \
            driver["consecutive_decline_count"] >= calc.DECLINE_SUSPENSION_THRESHOLD:
        cascades.suspend_driver(driver)

    return response.object_response(
        serializers.pick(assignment, serializers.POOL_ASSIGNMENT))


@bp.post("/pool-assignments/<assignment_id>/board")
@endpoint(["DriverUser"])
def board_assignment(assignment_id):
    assignment = get_assignment(assignment_id)
    block = _require_driver_of(assignment)

    if assignment["state"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE")
    if block is None or block["state"] != "OPEN":
        raise ApiError("ERR_INVALID_BLOCK_STATE")

    assignment["state"] = "ONBOARD"
    db.touch(assignment)

    trip = _trip_of(assignment)
    if trip is not None:
        trip["status"] = "PICKED_UP"
        trip["actual_pickup_utc"] = clock.now_raw()
        requested_dt = clock.parse_dt(trip["requested_pickup_utc"])
        trip["wait_minutes"] = max(0, calc.minutes_between(clock.now(), requested_dt))
        db.touch(trip)

    block_service.recompute_seq_pickup(block["id"])
    return response.object_response(
        serializers.pick(assignment, serializers.POOL_ASSIGNMENT))


@bp.post("/pool-assignments/<assignment_id>/complete")
@endpoint(["DriverUser"])
def complete_assignment(assignment_id):
    assignment = get_assignment(assignment_id)
    block = _require_driver_of(assignment)

    if assignment["state"] != "ONBOARD":
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE")

    # HOP 1 -- the block settles: capacity released, boardings counted
    assignment["state"] = "COMPLETED"
    db.touch(assignment)
    if block is not None:
        block_service.recompute_block(block)

    # HOP 2 -- the trip settles and the fare is charged
    trip = _trip_of(assignment)
    if trip is not None:
        trip["status"] = "COMPLETED"
        trip["actual_dropoff_utc"] = clock.now_raw()
        pickup_dt = clock.parse_dt(trip["actual_pickup_utc"])
        if pickup_dt is not None:
            trip["ride_minutes"] = calc.minutes_between(clock.now(), pickup_dt)
        zone = db.service_zones.get(trip["zone_id"])
        rider = db.riders.get(trip["rider_id"])
        if zone is not None and rider is not None:
            fares.settle(trip, zone, rider)
        db.touch(trip)
        metrics.recompute_zone(zone)

    return response.object_response(
        serializers.pick(assignment, serializers.POOL_ASSIGNMENT))


@bp.get("/pool-assignments/<assignment_id>")
@endpoint(ALL_ROLES)
def read_assignment(assignment_id):
    assignment = get_assignment(assignment_id)
    if middleware.role() == "DriverUser":
        _require_driver_of(assignment)
    elif middleware.role() == "Rider":
        trip = _trip_of(assignment)
        middleware.require_rider_owner(trip["rider_id"] if trip else None)
    return response.object_response(
        serializers.pick(assignment, serializers.POOL_ASSIGNMENT))


@bp.get("/pool-assignments")
@endpoint(ALL_ROLES)
def list_assignments():
    return listing.list_endpoint(
        db.pool_assignments.ordered(), serializers.POOL_ASSIGNMENT,
        {"block_id": "block_id", "trip_request_id": "trip_request_id",
         "state": "state", "offer_origin": "offer_origin"})


# --------------------------------------------------------------------------
# the fare ledger (append-only; discovery only)
# --------------------------------------------------------------------------

@bp.get("/fare-transactions/<row_id>")
@endpoint(ALL_ROLES)
def read_fare_transaction(row_id):
    row = db.fare_transactions.get(row_id)
    if row is None:
        raise ApiError("ERR_FARE_TRANSACTION_NOT_FOUND")
    middleware.require_rider_owner(row["rider_id"])
    return response.object_response(
        serializers.pick(row, serializers.FARE_TRANSACTION))


@bp.get("/fare-transactions")
@endpoint(ALL_ROLES)
def list_fare_transactions():
    return listing.list_endpoint(
        db.fare_transactions.ordered(), serializers.FARE_TRANSACTION,
        {"trip_request_id": "trip_request_id", "rider_id": "rider_id",
         "kind": "kind", "service_date": "service_date"})
