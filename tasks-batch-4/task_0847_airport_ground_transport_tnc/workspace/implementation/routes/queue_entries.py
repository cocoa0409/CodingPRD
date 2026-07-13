from datetime import timedelta

from flask import Blueprint, request

import serializers
import logic
import calc
from common import (
    authenticate, require_role, body_json, as_str, as_number, as_enum,
    must_exist, respond, parse_pagination, list_response,
)
from errors import ApiError
from store import db, base_record, now

bp = Blueprint("queue_entries", __name__)

QUEUE_ACTIONS = {"CANCEL", "EXIT"}


@bp.route("/v1/queue-entries", methods=["POST"])
def create_queue_entry():
    uid, role = authenticate()
    require_role(role, {"Operator"})
    body = body_json()
    staging_lot_id = as_str(body, "staging_lot_id")
    vehicle_id = as_str(body, "vehicle_id")
    lat = as_number(body, "lat")
    lng = as_number(body, "lng")

    # existence, left-to-right: staging_lot_id then vehicle_id
    lot = must_exist(db.staging_lots, staging_lot_id)
    vehicle = must_exist(db.vehicles, vehicle_id)

    # ownership: operator must own the vehicle
    if vehicle["operator_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Operator does not own this vehicle")

    # guard order per PRD 3.3
    if vehicle["status"] != "ACTIVE":
        raise ApiError("ERR_VEHICLE_NOT_ACTIVE", 409, "Vehicle is not ACTIVE")

    has_active_permit = any(
        p["vehicle_id"] == vehicle_id and p["permit_status"] == "ACTIVE"
        for p in db.permits.values()
    )
    if not has_active_permit:
        raise ApiError("ERR_VEHICLE_PERMIT_INVALID", 409, "Vehicle has no ACTIVE permit")

    dist = calc.haversine_m(lat, lng, lot["geofence_center_lat"], lot["geofence_center_lng"])
    if dist > lot["geofence_radius_m"]:
        raise ApiError("ERR_GEOFENCE_VIOLATION", 422, "Join location outside geofence")

    already_waiting = any(
        q["vehicle_id"] == vehicle_id and q["status"] == "WAITING"
        for q in db.queue_entries.values()
    )
    if already_waiting:
        raise ApiError("ERR_ALREADY_IN_QUEUE", 409, "Vehicle already has a WAITING queue entry")

    # staging cooldown: >= 30 min past the most recent prior exit
    prior_exits = [
        q["exit_ts"]
        for q in db.queue_entries.values()
        if q["vehicle_id"] == vehicle_id
        and q["status"] in ("RELEASED", "EXITED", "CANCELLED")
        and q["exit_ts"] is not None
    ]
    if prior_exits:
        latest_exit = max(prior_exits)
        if now() - latest_exit < timedelta(minutes=calc.STAGING_COOLDOWN_MINUTES):
            raise ApiError("ERR_STAGING_BUFFER_VIOLATION", 409, "Staging cooldown not elapsed")

    if logic.waiting_count(staging_lot_id) >= lot["capacity"]:
        raise ApiError("ERR_LOT_CAPACITY_EXCEEDED", 409, "Lot at capacity")

    rec = base_record()
    rec.update({
        "staging_lot_id": staging_lot_id,
        "vehicle_id": vehicle_id,
        "position": logic.waiting_count(staging_lot_id) + 1,
        "status": "WAITING",
        "enter_ts": now(),
        "exit_ts": None,
    })
    db.queue_entries[rec["id"]] = rec
    return respond(serializers.queue_entry(rec), "object", 201)


@bp.route("/v1/queue-entries/<queue_entry_id>", methods=["GET"])
def get_queue_entry(queue_entry_id):
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority", "Operator", "CurbCoordinator"})
    q = must_exist(db.queue_entries, queue_entry_id)
    return respond(serializers.queue_entry(q), "object", 200)


@bp.route("/v1/queue-entries", methods=["GET"])
def list_queue_entries():
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority", "Operator", "CurbCoordinator"})
    limit, offset = parse_pagination()
    staging_lot_id = request.args.get("staging_lot_id")
    vehicle_id = request.args.get("vehicle_id")
    status = request.args.get("status")
    items = [
        q for q in db.queue_entries.values()
        if (staging_lot_id is None or q["staging_lot_id"] == staging_lot_id)
        and (vehicle_id is None or q["vehicle_id"] == vehicle_id)
        and (status is None or q["status"] == status)
    ]
    return list_response(items, serializers.queue_entry, limit, offset)


@bp.route("/v1/queue-entries/<queue_entry_id>/transitions", methods=["POST"])
def queue_entry_transition(queue_entry_id):
    uid, role = authenticate()
    require_role(role, {"Operator"})
    body = body_json()
    action = as_enum(body, "action", QUEUE_ACTIONS)

    q = must_exist(db.queue_entries, queue_entry_id)

    # ownership: operator must own the queued vehicle
    vehicle = db.vehicles.get(q["vehicle_id"])
    if vehicle is None or vehicle["operator_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Operator does not own this queue entry")

    if q["status"] != "WAITING":
        raise ApiError("ERR_INVALID_STATE", 409, "Queue entry not WAITING")

    logic.leave_waiting(q, "CANCELLED" if action == "CANCEL" else "EXITED")
    return respond(serializers.queue_entry(q), "object", 200)
