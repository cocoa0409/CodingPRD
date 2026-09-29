"""Trip intake, real-time matching, cancellation and fare reversal."""
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
from services import cascades, fares, offers

bp = Blueprint("trips", __name__)

CANCELLABLE = ("RECEIVED", "MATCHING", "OFFERED", "ASSIGNED")


def get_trip(trip_id):
    trip = db.trip_requests.get(trip_id)
    if trip is None:
        raise ApiError("ERR_TRIP_REQUEST_NOT_FOUND")
    return trip


@bp.post("/trip-requests")
@endpoint(["Rider", "Dispatcher"])
def create_trip():
    body = validation.get_body()

    # priority 5 -- body reference existence, in declared input order
    zone_raw = validation.raw_fk(body, "zone_id")
    zone = db.service_zones.get(zone_raw) if zone_raw is not None else None
    if zone_raw is not None and zone is None:
        raise ApiError("ERR_SERVICE_ZONE_NOT_FOUND")
    rider_raw = validation.raw_fk(body, "rider_id")
    rider = db.riders.get(rider_raw) if rider_raw is not None else None
    if rider_raw is not None and rider is None:
        raise ApiError("ERR_RIDER_NOT_FOUND")
    origin_raw = validation.raw_fk(body, "origin_stop_id")
    origin = db.virtual_stops.get(origin_raw) if origin_raw is not None else None
    if origin_raw is not None and origin is None:
        raise ApiError("ERR_VIRTUAL_STOP_NOT_FOUND")
    destination_raw = validation.raw_fk(body, "destination_stop_id")
    destination = (db.virtual_stops.get(destination_raw)
                   if destination_raw is not None else None)
    if destination_raw is not None and destination is None:
        raise ApiError("ERR_VIRTUAL_STOP_NOT_FOUND")
    connection_raw = validation.raw_fk(body, "connection_id")
    connection = (db.transit_connections.get(connection_raw)
                  if connection_raw is not None else None)
    if connection_raw is not None and connection is None:
        raise ApiError("ERR_TRANSIT_CONNECTION_NOT_FOUND")

    # priority 6 -- a Rider may only book for themselves
    if rider_raw is not None:
        middleware.require_rider_owner(rider_raw)

    # priority 7 -- request shape
    validation.req_str(body, "zone_id")
    validation.req_str(body, "rider_id")
    validation.req_str(body, "origin_stop_id")
    validation.req_str(body, "destination_stop_id")
    pickup_raw, pickup_dt = validation.req_datetime(body, "requested_pickup_utc")
    party_size = validation.opt_int(body, "party_size", 1, 1, 6)
    wav_requested = validation.opt_bool(body, "wav_required", False)
    if origin["id"] == destination["id"]:
        validation.invalid("destination_stop_id must differ from origin_stop_id.")

    # priority 12 -- the zone must be ACTIVE for intake
    if zone["status"] != "ACTIVE":
        raise ApiError("ERR_ZONE_NOT_ACTIVE")

    # priority 15 -- cross-zone consistency
    for referenced in (rider, origin, destination, connection):
        if referenced is not None and referenced["zone_id"] != zone["id"]:
            raise ApiError("ERR_ZONE_MISMATCH")

    # priority 17 -- both stops approved
    if origin["status"] != "APPROVED" or destination["status"] != "APPROVED":
        raise ApiError("ERR_STOP_NOT_APPROVED")

    wav_required = bool(wav_requested) or rider["mobility_device"] == "WHEELCHAIR"

    # priority 19 -- accessible path at both ends
    if wav_required:
        if origin["accessibility"] != "ACCESSIBLE_PATH" or \
                destination["accessibility"] != "ACCESSIBLE_PATH":
            raise ApiError("ERR_STOP_NOT_ACCESSIBLE")

    # priority 25 -- the guaranteed transfer window
    if connection is not None:
        departure = clock.parse_dt(connection["scheduled_departure_utc"])
        delta_seconds = abs((pickup_dt - departure).total_seconds())
        if delta_seconds > connection["guaranteed_transfer_buffer_minutes"] * 60:
            raise ApiError("ERR_TRANSFER_WINDOW_MISSED")

    trip = db.base_record()
    trip.update({
        "zone_id": zone["id"],
        "rider_id": rider["id"],
        "origin_stop_id": origin["id"],
        "destination_stop_id": destination["id"],
        "connection_id": connection["id"] if connection is not None else None,
        "assigned_block_id": None,
        "requested_pickup_utc": pickup_raw,
        "party_size": party_size,
        "wav_required": wav_required,
        "status": "RECEIVED",
        "fare_status": "UNPRICED",
        "no_service_reason": None,
        "match_attempt_count": 0,
        "baseline_direct_minutes": calc.baseline_direct_minutes(
            origin["corridor_index"], destination["corridor_index"]),
        "projected_detour_minutes": None,
        "promised_pickup_utc": None,
        "promised_dropoff_utc": None,
        "actual_pickup_utc": None,
        "actual_dropoff_utc": None,
        "wait_minutes": None,
        "ride_minutes": None,
        "quoted_fare_cents": None,
        "charged_fare_cents": None,
        "applied_cap": None,
    })
    db.trip_requests.add(trip)
    return response.created(serializers.pick(trip, serializers.TRIP_REQUEST))


@bp.post("/trip-requests/<trip_id>/match")
@endpoint(["Dispatcher"])
def match_trip(trip_id):
    trip = get_trip(trip_id)
    if trip["status"] not in ("RECEIVED", "MATCHING"):
        raise ApiError("ERR_INVALID_TRIP_STATE")
    zone = db.service_zones.get(trip["zone_id"])
    if zone is None or zone["status"] != "ACTIVE":
        raise ApiError("ERR_ZONE_NOT_ACTIVE")

    pool = offers.candidates(trip)
    if pool:
        block, score = offers.select_winner(trip, pool)
        offers.create_offer(trip, block, "AUTO_MATCH", score)
    elif trip["match_attempt_count"] >= calc.MAX_MATCH_ATTEMPTS:
        trip["status"] = "NO_SERVICE"
        trip["no_service_reason"] = "NO_ELIGIBLE_BLOCK"
        db.touch(trip)
        from services import metrics
        metrics.recompute_zone(zone)
    else:
        trip["status"] = "MATCHING"
        db.touch(trip)

    return response.object_response(
        serializers.pick(trip, serializers.TRIP_REQUEST))


@bp.post("/trip-requests/<trip_id>/cancel")
@endpoint(["Rider", "Dispatcher"])
def cancel_trip(trip_id):
    trip = get_trip(trip_id)
    middleware.require_rider_owner(trip["rider_id"])
    body = validation.get_body()
    validation.opt_str(body, "note", min_len=0)

    if trip["status"] not in CANCELLABLE:
        raise ApiError("ERR_INVALID_TRIP_STATE")

    if trip["status"] in ("OFFERED", "ASSIGNED"):
        cascades.release_live_assignment_for_trip(trip)
        cascades.clear_trip_booking(trip)

    trip["status"] = "CANCELLED"
    db.touch(trip)
    return response.object_response(
        serializers.pick(trip, serializers.TRIP_REQUEST))


@bp.post("/trip-requests/<trip_id>/refund")
@endpoint(["Dispatcher"])
def refund_trip(trip_id):
    trip = get_trip(trip_id)
    body = validation.get_body()
    validation.req_str(body, "reason")

    if trip["fare_status"] != "CHARGED":
        raise ApiError("ERR_TRIP_NOT_CHARGED")

    rider = db.riders.get(trip["rider_id"])
    fares.refund(trip, rider)
    db.touch(trip)
    return response.object_response(
        serializers.pick(trip, serializers.TRIP_REQUEST))


@bp.get("/trip-requests/<trip_id>")
@endpoint(ALL_ROLES)
def read_trip(trip_id):
    trip = get_trip(trip_id)
    middleware.require_rider_owner(trip["rider_id"])
    return response.object_response(
        serializers.pick(trip, serializers.TRIP_REQUEST))


@bp.get("/trip-requests")
@endpoint(ALL_ROLES)
def list_trips():
    return listing.list_endpoint(
        db.trip_requests.ordered(), serializers.TRIP_REQUEST,
        {"zone_id": "zone_id", "rider_id": "rider_id",
         "origin_stop_id": "origin_stop_id",
         "destination_stop_id": "destination_stop_id",
         "connection_id": "connection_id",
         "assigned_block_id": "assigned_block_id",
         "status": "status", "fare_status": "fare_status",
         "wav_required": ("wav_required", "bool")})
