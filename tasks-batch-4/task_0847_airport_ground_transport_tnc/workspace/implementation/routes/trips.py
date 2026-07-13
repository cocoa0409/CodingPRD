from flask import Blueprint, request

import serializers
import logic
import calc
from common import (
    authenticate, require_role, body_json, as_str, as_bool, as_enum,
    must_exist, respond, parse_pagination, list_response,
)
from errors import ApiError
from store import db, base_record, touch, now

bp = Blueprint("trips", __name__)

TRIP_ACTIONS = {"PICKUP", "COMPLETE", "CANCEL", "VOID"}
OPERATOR_ACTIONS = {"PICKUP", "COMPLETE", "CANCEL"}


@bp.route("/v1/trips", methods=["POST"])
def dispatch_trip():
    uid, role = authenticate()
    require_role(role, {"Operator"})
    body = body_json()
    vehicle_id = as_str(body, "vehicle_id")
    staging_lot_id = as_str(body, "staging_lot_id")
    trip_kind = as_enum(body, "trip_kind", {"PICKUP", "DEADHEAD"}, required=False, default="PICKUP")
    is_wav = as_bool(body, "is_wheelchair_trip", default=False)

    # existence, left-to-right: vehicle_id then staging_lot_id
    vehicle = must_exist(db.vehicles, vehicle_id)
    must_exist(db.staging_lots, staging_lot_id)

    # ownership
    if vehicle["operator_id"] != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Operator does not own this vehicle")

    # guard order per PRD 3.4
    if vehicle["status"] != "ACTIVE":
        raise ApiError("ERR_VEHICLE_NOT_ACTIVE", 409, "Vehicle is not ACTIVE")

    op = db.operators[vehicle["operator_id"]]
    if op["status"] != "ACTIVE":
        raise ApiError("ERR_OPERATOR_NOT_ACTIVE", 409, "Owning operator is not ACTIVE")

    has_active_permit = any(
        p["vehicle_id"] == vehicle_id and p["permit_status"] == "ACTIVE"
        for p in db.permits.values()
    )
    if not has_active_permit:
        raise ApiError("ERR_VEHICLE_PERMIT_INVALID", 409, "Vehicle has no ACTIVE permit")

    head_entry = None
    for q in db.queue_entries.values():
        if (q["vehicle_id"] == vehicle_id and q["staging_lot_id"] == staging_lot_id
                and q["status"] == "WAITING"):
            head_entry = q
            break
    if head_entry is None or head_entry["position"] != 1:
        raise ApiError("ERR_NOT_QUEUE_HEAD", 409, "Vehicle is not at the head of its lot queue")

    rec = base_record()
    dispatch_ts = now()
    provisional = calc.trip_fee(op["operator_type"], trip_kind, is_wav, dispatch_ts)
    rec.update({
        "operator_id": vehicle["operator_id"],
        "vehicle_id": vehicle_id,
        "trip_kind": trip_kind,
        "is_wheelchair_trip": is_wav,
        "status": "DISPATCHED",
        "dispatch_ts": dispatch_ts,
        "pickup_ts": None,
        "complete_ts": None,
        "provisional_fee_cents": provisional,
        "final_fee_cents": None,
        "settlement_statement_id": None,
    })
    db.trips[rec["id"]] = rec

    # release the head queue entry with FIFO renumber
    logic.leave_waiting(head_entry, "RELEASED")

    return respond(serializers.trip(rec), "object", 201)


@bp.route("/v1/trips/<trip_id>", methods=["GET"])
def get_trip(trip_id):
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority", "Operator", "CurbCoordinator"})
    t = must_exist(db.trips, trip_id)
    return respond(serializers.trip(t), "object", 200)


@bp.route("/v1/trips", methods=["GET"])
def list_trips():
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority", "Operator", "CurbCoordinator"})
    limit, offset = parse_pagination()
    operator_id = request.args.get("operator_id")
    vehicle_id = request.args.get("vehicle_id")
    settlement_statement_id = request.args.get("settlement_statement_id")
    status = request.args.get("status")
    items = [
        t for t in db.trips.values()
        if (operator_id is None or t["operator_id"] == operator_id)
        and (vehicle_id is None or t["vehicle_id"] == vehicle_id)
        and (settlement_statement_id is None or t["settlement_statement_id"] == settlement_statement_id)
        and (status is None or t["status"] == status)
    ]
    return list_response(items, serializers.trip, limit, offset)


@bp.route("/v1/trips/<trip_id>/transitions", methods=["POST"])
def trip_transition(trip_id):
    uid, role = authenticate()
    require_role(role, {"Operator", "AirportAuthority"})
    body = body_json()
    action = as_enum(body, "action", TRIP_ACTIONS)

    t = must_exist(db.trips, trip_id)

    # action-specific authorization
    if action in OPERATOR_ACTIONS:
        if role != "Operator":
            raise ApiError("ERR_UNAUTHORIZED", 403, "Only the operator may perform this action")
        if t["operator_id"] != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "Operator does not own this trip")
    else:  # VOID
        if role != "AirportAuthority":
            raise ApiError("ERR_UNAUTHORIZED", 403, "Only the airport authority may void a trip")

    op = db.operators[t["operator_id"]]

    if action == "PICKUP":
        if t["status"] != "DISPATCHED":
            raise ApiError("ERR_INVALID_STATE", 409, "Trip not DISPATCHED")
        t["status"] = "PICKED_UP"
        t["pickup_ts"] = now()
        touch(t)
    elif action == "COMPLETE":
        if t["status"] != "PICKED_UP":
            raise ApiError("ERR_INVALID_STATE", 409, "Trip not PICKED_UP")
        t["status"] = "COMPLETED"
        t["complete_ts"] = now()
        t["final_fee_cents"] = calc.trip_fee(
            op["operator_type"], t["trip_kind"], t["is_wheelchair_trip"], t["pickup_ts"]
        )
        touch(t)
        logic.recompute_operator_points(op)  # outstanding recompute -> operator mutation
        logic.release_curb_for_trip(t)
    elif action == "CANCEL":
        if t["status"] != "DISPATCHED":
            raise ApiError("ERR_INVALID_STATE", 409, "Trip not DISPATCHED")
        t["status"] = "CANCELLED"
        touch(t)
        logic.release_curb_for_trip(t)
    elif action == "VOID":
        if t["status"] != "COMPLETED":
            raise ApiError("ERR_INVALID_STATE", 409, "Trip not COMPLETED")
        if t["settlement_statement_id"] is not None:
            raise ApiError("ERR_TRIP_ALREADY_SETTLED", 409, "Trip already swept into a statement")
        t["status"] = "VOIDED"
        touch(t)
        logic.recompute_operator_points(op)  # outstanding recompute -> operator mutation

    return respond(serializers.trip(t), "object", 200)
