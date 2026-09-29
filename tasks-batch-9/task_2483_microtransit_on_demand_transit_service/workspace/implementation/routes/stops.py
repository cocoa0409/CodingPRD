"""Virtual stops along the corridor and the fixed-route transit connections."""
from flask import Blueprint

import db
import listing
import response
import serializers
import validation
from errors import ApiError
from middleware import ALL_ROLES, endpoint

bp = Blueprint("stops", __name__)

ACCESSIBILITY = ("ACCESSIBLE_PATH", "STAIRS_ONLY", "UNKNOWN")
MODES = ("RAIL", "BUS")
LIVE_TRIP_STATUSES = ("RECEIVED", "MATCHING", "OFFERED", "ASSIGNED", "PICKED_UP")
CONFIGURABLE_ZONE_STATES = ("DRAFT", "ACTIVE")


def _zone(zone_id):
    zone = db.service_zones.get(zone_id)
    if zone is None:
        raise ApiError("ERR_SERVICE_ZONE_NOT_FOUND")
    return zone


def get_stop(stop_id):
    stop = db.virtual_stops.get(stop_id)
    if stop is None:
        raise ApiError("ERR_VIRTUAL_STOP_NOT_FOUND")
    return stop


def _require_configurable(zone):
    if zone["status"] not in CONFIGURABLE_ZONE_STATES:
        raise ApiError("ERR_ZONE_NOT_ACTIVE")


# --------------------------------------------------------------------------
# virtual stops
# --------------------------------------------------------------------------

@bp.post("/virtual-stops")
@endpoint(["ZoneAdmin"])
def create_stop():
    body = validation.get_body()

    # priority 5 -- body reference existence, in declared input order
    zone_raw = validation.raw_fk(body, "zone_id")
    zone = _zone(zone_raw) if zone_raw is not None else None
    paired_raw = validation.raw_fk(body, "paired_stop_id")
    paired = get_stop(paired_raw) if paired_raw is not None else None

    # priority 7 -- request shape
    zone_id = validation.req_str(body, "zone_id")
    stop_code = validation.req_str(body, "stop_code")
    corridor_index = validation.req_int(body, "corridor_index", 0, 500)
    walk_shed_meters = validation.req_int(body, "walk_shed_meters", 0)
    accessibility = validation.opt_enum(body, "accessibility", ACCESSIBILITY,
                                        "UNKNOWN")
    if zone is None:
        zone = _zone(zone_id)

    # priority 9 -- stop pairing validity
    if paired is not None:
        if paired["zone_id"] != zone["id"] or paired["status"] == "RETIRED":
            raise ApiError("ERR_PAIRED_STOP_INVALID")

    # priority 13 -- zone must be DRAFT or ACTIVE
    _require_configurable(zone)

    stop = db.base_record()
    stop.update({
        "zone_id": zone["id"],
        "stop_code": stop_code,
        "corridor_index": corridor_index,
        "walk_shed_meters": walk_shed_meters,
        "accessibility": accessibility,
        "paired_stop_id": paired["id"] if paired is not None else None,
        "status": "PROPOSED",
    })
    db.virtual_stops.add(stop)
    return response.created(serializers.pick(stop, serializers.VIRTUAL_STOP))


@bp.post("/virtual-stops/<stop_id>/approve")
@endpoint(["ZoneAdmin"])
def approve_stop(stop_id):
    stop = get_stop(stop_id)
    if stop["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STOP_STATE")
    zone = _zone(stop["zone_id"])
    _require_configurable(zone)
    if stop["walk_shed_meters"] > zone["max_walk_meters"]:
        raise ApiError("ERR_WALK_DISTANCE_EXCEEDED")
    stop["status"] = "APPROVED"
    db.touch(stop)
    return response.object_response(
        serializers.pick(stop, serializers.VIRTUAL_STOP))


@bp.post("/virtual-stops/<stop_id>/retire")
@endpoint(["ZoneAdmin"])
def retire_stop(stop_id):
    stop = get_stop(stop_id)
    if stop["status"] not in ("PROPOSED", "APPROVED"):
        raise ApiError("ERR_INVALID_STOP_STATE")
    for trip in db.trip_requests.values():
        if trip["status"] not in LIVE_TRIP_STATUSES:
            continue
        if stop["id"] in (trip["origin_stop_id"], trip["destination_stop_id"]):
            raise ApiError("ERR_STOP_IN_USE")

    was_approved = stop["status"] == "APPROVED"
    stop["status"] = "RETIRED"
    db.touch(stop)

    if was_approved:
        pointing = [s for s in db.virtual_stops.values()
                    if s["paired_stop_id"] == stop["id"]]
        for other in db.by_created_at(pointing):
            other["paired_stop_id"] = None
            db.touch(other)

    return response.object_response(
        serializers.pick(stop, serializers.VIRTUAL_STOP))


@bp.get("/virtual-stops/<stop_id>")
@endpoint(ALL_ROLES)
def read_stop(stop_id):
    stop = get_stop(stop_id)
    return response.object_response(
        serializers.pick(stop, serializers.VIRTUAL_STOP))


@bp.get("/virtual-stops")
@endpoint(ALL_ROLES)
def list_stops():
    return listing.list_endpoint(
        db.virtual_stops.ordered(), serializers.VIRTUAL_STOP,
        {"zone_id": "zone_id", "paired_stop_id": "paired_stop_id",
         "status": "status", "accessibility": "accessibility"})


# --------------------------------------------------------------------------
# transit connections
# --------------------------------------------------------------------------

def get_connection(connection_id):
    connection = db.transit_connections.get(connection_id)
    if connection is None:
        raise ApiError("ERR_TRANSIT_CONNECTION_NOT_FOUND")
    return connection


@bp.post("/transit-connections")
@endpoint(["ZoneAdmin"])
def create_connection():
    body = validation.get_body()

    zone_raw = validation.raw_fk(body, "zone_id")
    zone = _zone(zone_raw) if zone_raw is not None else None
    stop_raw = validation.raw_fk(body, "stop_id")
    stop = get_stop(stop_raw) if stop_raw is not None else None

    zone_id = validation.req_str(body, "zone_id")
    stop_id = validation.req_str(body, "stop_id")
    mode = validation.req_enum(body, "mode", MODES)
    route_code = validation.req_str(body, "route_code")
    departure_raw, _departure = validation.req_datetime(
        body, "scheduled_departure_utc")
    buffer_minutes = validation.req_int(
        body, "guaranteed_transfer_buffer_minutes", 0, 60)
    credit_cents = validation.req_int(body, "transfer_credit_cents", 0)
    if zone is None:
        zone = _zone(zone_id)
    if stop is None:
        stop = get_stop(stop_id)

    _require_configurable(zone)

    if stop["zone_id"] != zone["id"]:
        raise ApiError("ERR_ZONE_MISMATCH")

    connection = db.base_record()
    connection.update({
        "zone_id": zone["id"],
        "stop_id": stop["id"],
        "mode": mode,
        "route_code": route_code,
        "scheduled_departure_utc": departure_raw,
        "guaranteed_transfer_buffer_minutes": buffer_minutes,
        "transfer_credit_cents": credit_cents,
    })
    db.transit_connections.add(connection)
    return response.created(
        serializers.pick(connection, serializers.TRANSIT_CONNECTION))


@bp.get("/transit-connections/<connection_id>")
@endpoint(ALL_ROLES)
def read_connection(connection_id):
    connection = get_connection(connection_id)
    return response.object_response(
        serializers.pick(connection, serializers.TRANSIT_CONNECTION))


@bp.get("/transit-connections")
@endpoint(ALL_ROLES)
def list_connections():
    return listing.list_endpoint(
        db.transit_connections.ordered(), serializers.TRANSIT_CONNECTION,
        {"zone_id": "zone_id", "stop_id": "stop_id", "mode": "mode"})
