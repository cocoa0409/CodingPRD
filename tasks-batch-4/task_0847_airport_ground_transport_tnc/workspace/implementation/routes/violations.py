from datetime import timedelta

from flask import Blueprint, request

import serializers
import logic
import calc
from common import (
    authenticate, require_role, body_json, as_str, as_enum,
    must_exist, respond, parse_pagination, list_response,
)
from errors import ApiError
from store import db, base_record, touch, now

bp = Blueprint("violations", __name__)

VIOLATION_ACTIONS = {"ASSESS", "DISMISS", "UPHOLD", "OVERTURN", "WAIVE", "APPEAL", "PAY"}
AUTHORITY_ACTIONS = {"ASSESS", "DISMISS", "UPHOLD", "OVERTURN", "WAIVE"}
OPERATOR_ACTIONS = {"APPEAL", "PAY"}


@bp.route("/v1/violations", methods=["POST"])
def create_violation():
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority"})
    body = body_json()
    operator_id = as_str(body, "operator_id")
    violation_type = as_enum(body, "violation_type", calc.VALID_VIOLATION_TYPES)
    trip_id = as_str(body, "trip_id", required=False, default=None)

    # existence, left-to-right: operator_id then trip_id (if present)
    must_exist(db.operators, operator_id)
    if trip_id is not None:
        must_exist(db.trips, trip_id)

    rec = base_record()
    rec.update({
        "operator_id": operator_id,
        "trip_id": trip_id,
        "violation_type": violation_type,
        "source": "MANUAL",
        "penalty_points": calc.PENALTY_POINTS_BY_TYPE[violation_type],
        "fine_cents": calc.FINE_CENTS_BY_TYPE[violation_type],
        "status": "OPEN",
        "assessed_at": None,
    })
    db.violations[rec["id"]] = rec
    return respond(serializers.violation(rec), "object", 201)


@bp.route("/v1/violations/<violation_id>", methods=["GET"])
def get_violation(violation_id):
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority", "Operator", "CurbCoordinator"})
    v = must_exist(db.violations, violation_id)
    return respond(serializers.violation(v), "object", 200)


@bp.route("/v1/violations", methods=["GET"])
def list_violations():
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority", "Operator", "CurbCoordinator"})
    limit, offset = parse_pagination()
    operator_id = request.args.get("operator_id")
    trip_id = request.args.get("trip_id")
    status = request.args.get("status")
    items = [
        v for v in db.violations.values()
        if (operator_id is None or v["operator_id"] == operator_id)
        and (trip_id is None or v["trip_id"] == trip_id)
        and (status is None or v["status"] == status)
    ]
    return list_response(items, serializers.violation, limit, offset)


@bp.route("/v1/violations/<violation_id>/transitions", methods=["POST"])
def violation_transition(violation_id):
    uid, role = authenticate()
    require_role(role, {"AirportAuthority", "Operator"})
    body = body_json()
    action = as_enum(body, "action", VIOLATION_ACTIONS)

    v = must_exist(db.violations, violation_id)

    # action-specific authorization
    if action in AUTHORITY_ACTIONS:
        if role != "AirportAuthority":
            raise ApiError("ERR_UNAUTHORIZED", 403, "Only the airport authority may perform this action")
    else:  # APPEAL / PAY
        if role != "Operator":
            raise ApiError("ERR_UNAUTHORIZED", 403, "Only the operator may perform this action")
        if v["operator_id"] != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "Operator does not own this violation")

    op = db.operators[v["operator_id"]]
    status = v["status"]

    if action == "ASSESS":
        if status != "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409, "Violation not OPEN")
        v["status"] = "ASSESSED"
        v["assessed_at"] = now()
        touch(v)
        logic.recompute_operator_points(op)
        logic.auto_suspend_if_threshold(op)
    elif action == "DISMISS":
        if status != "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409, "Violation not OPEN")
        v["status"] = "DISMISSED"
        touch(v)
    elif action == "APPEAL":
        if status != "ASSESSED":
            raise ApiError("ERR_INVALID_STATE", 409, "Violation not ASSESSED")
        if now() - v["assessed_at"] > timedelta(days=calc.APPEAL_WINDOW_DAYS):
            raise ApiError("ERR_APPEAL_WINDOW_CLOSED", 409, "Appeal window has closed")
        v["status"] = "APPEALED"
        touch(v)
    elif action == "UPHOLD":
        if status != "APPEALED":
            raise ApiError("ERR_INVALID_STATE", 409, "Violation not APPEALED")
        v["status"] = "UPHELD"
        touch(v)
        logic.recompute_operator_points(op)
        logic.auto_suspend_if_threshold(op)
    elif action == "OVERTURN":
        if status != "APPEALED":
            raise ApiError("ERR_INVALID_STATE", 409, "Violation not APPEALED")
        v["status"] = "OVERTURNED"
        touch(v)
        logic.recompute_operator_points(op)
    elif action == "WAIVE":
        if status != "ASSESSED":
            raise ApiError("ERR_INVALID_STATE", 409, "Violation not ASSESSED")
        v["status"] = "WAIVED"
        touch(v)
        logic.recompute_operator_points(op)
    elif action == "PAY":
        if status not in ("ASSESSED", "UPHELD"):
            raise ApiError("ERR_INVALID_STATE", 409, "Violation not payable")
        v["status"] = "PAID"
        touch(v)

    return respond(serializers.violation(v), "object", 200)
