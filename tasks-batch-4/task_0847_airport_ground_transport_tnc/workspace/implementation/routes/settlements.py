from flask import Blueprint, request

import serializers
import logic
from common import (
    authenticate, require_role, body_json, as_str, as_int, as_enum,
    must_exist, respond, parse_pagination, list_response,
)
from errors import ApiError
from store import db, base_record, touch, now

bp = Blueprint("settlements", __name__)

SETTLEMENT_ACTIONS = {"CLOSE", "SETTLE"}


@bp.route("/v1/settlements", methods=["POST"])
def create_settlement():
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority"})
    body = body_json()
    operator_id = as_str(body, "operator_id")
    period_year = as_int(body, "period_year")
    period_month = as_int(body, "period_month")
    if period_month < 1 or period_month > 12:
        raise ApiError("ERR_VALIDATION", 400, "period_month must be between 1 and 12")

    must_exist(db.operators, operator_id)

    for s in db.settlements.values():
        if (s["operator_id"] == operator_id and s["period_year"] == period_year
                and s["period_month"] == period_month):
            raise ApiError("ERR_DUPLICATE_SETTLEMENT_PERIOD", 409,
                           "A statement for that operator+year+month already exists")

    rec = base_record()
    rec.update({
        "operator_id": operator_id,
        "period_year": period_year,
        "period_month": period_month,
        "status": "OPEN",
        "gross_fees_cents": 0,
        "admin_fee_cents": 0,
        "wav_incentive_credit_cents": 0,
        "net_due_cents": 0,
        "total_trip_count": 0,
        "wav_trip_count": 0,
        "closed_at": None,
        "settled_at": None,
    })
    db.settlements[rec["id"]] = rec
    return respond(serializers.settlement(rec), "object", 201)


@bp.route("/v1/settlements/<settlement_id>", methods=["GET"])
def get_settlement(settlement_id):
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority", "Operator", "CurbCoordinator"})
    s = must_exist(db.settlements, settlement_id)
    return respond(serializers.settlement(s), "object", 200)


@bp.route("/v1/settlements", methods=["GET"])
def list_settlements():
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority", "Operator", "CurbCoordinator"})
    limit, offset = parse_pagination()
    operator_id = request.args.get("operator_id")
    items = [s for s in db.settlements.values()
             if operator_id is None or s["operator_id"] == operator_id]
    return list_response(items, serializers.settlement, limit, offset)


@bp.route("/v1/settlements/<settlement_id>/transitions", methods=["POST"])
def settlement_transition(settlement_id):
    uid, role = authenticate()
    require_role(role, {"AirportAuthority", "Operator"})
    body = body_json()
    action = as_enum(body, "action", SETTLEMENT_ACTIONS)

    s = must_exist(db.settlements, settlement_id)
    op = db.operators[s["operator_id"]]

    if action == "CLOSE":
        if role != "AirportAuthority":
            raise ApiError("ERR_UNAUTHORIZED", 403, "Only the airport authority may close a statement")
        if s["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", 409, "Statement not OPEN")
        logic.close_settlement(s, op)
    else:  # SETTLE
        if role != "Operator":
            raise ApiError("ERR_UNAUTHORIZED", 403, "Only the operator may settle a statement")
        if s["operator_id"] != uid:
            raise ApiError("ERR_UNAUTHORIZED", 403, "Operator does not own this statement")
        payment = as_int(body, "payment_amount_cents")
        if s["status"] != "CLOSED":
            raise ApiError("ERR_INVALID_STATE", 409, "Statement not CLOSED")
        if payment != s["net_due_cents"]:
            raise ApiError("ERR_SETTLEMENT_AMOUNT_MISMATCH", 402,
                           "payment_amount_cents does not equal net_due_cents")
        s["status"] = "SETTLED"
        s["settled_at"] = now()
        touch(s)

    return respond(serializers.settlement(s), "object", 200)
