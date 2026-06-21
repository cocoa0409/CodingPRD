"""Passenger and TravelPass routes (PRD 3.12, 3.10)."""
from flask import Blueprint, request

import db
from errors import err
from response import success
from middleware import auth
from helpers import parse_pagination, paginate, get_json_body
from timeutil import parse_date
import serializers as ser
from services import passes as pass_svc

bp = Blueprint("passengers", __name__)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


# ---------------------------------------------------------------------------
# Passenger (PRD 3.12)
# ---------------------------------------------------------------------------
@bp.route("/v1/passengers", methods=["POST"])
def create_passenger():
    auth({"SupportAgent", "Passenger"})
    body = get_json_body()
    full_name = body.get("full_name")
    email = body.get("email")
    if not isinstance(full_name, str) or not full_name:
        raise err("ERR_INVALID_REQUEST", "full_name is required")
    if not isinstance(email, str) or not email:
        raise err("ERR_INVALID_REQUEST", "email is required")
    needs_acc = body.get("needs_accessibility", False)
    if not isinstance(needs_acc, bool):
        raise err("ERR_INVALID_REQUEST", "needs_accessibility must be a boolean")

    # Unique email among passengers (PRD 3.12).
    for p in db.passengers.values():
        if p["email"] == email:
            raise err("ERR_DUPLICATE_EMAIL", "email already registered")

    pid = db.new_id()
    rec = {
        "id": pid, "full_name": full_name, "email": email,
        "needs_accessibility": needs_acc,
    }
    db.stamp_create(rec)
    db.passengers[pid] = rec
    return success(ser.passenger_out(rec), 201)


@bp.route("/v1/passengers/<passenger_id>", methods=["GET"])
def get_passenger(passenger_id):
    auth({"Passenger", "SupportAgent"})
    rec = db.passengers.get(passenger_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "passenger not found")
    return success(ser.passenger_out(rec), 200)


# ---------------------------------------------------------------------------
# TravelPass (PRD 3.10)
# ---------------------------------------------------------------------------
@bp.route("/v1/passes", methods=["POST"])
def create_pass():
    auth({"SupportAgent"})
    body = get_json_body()
    passenger_id = body.get("passenger_id")
    operator_id = body.get("operator_id")
    if not isinstance(passenger_id, str) or not passenger_id:
        raise err("ERR_INVALID_REQUEST", "passenger_id is required")
    if db.passengers.get(passenger_id) is None:
        raise err("ERR_NOT_FOUND", "passenger not found")
    if not isinstance(operator_id, str) or not operator_id:
        raise err("ERR_INVALID_REQUEST", "operator_id is required")
    if db.operators.get(operator_id) is None:
        raise err("ERR_NOT_FOUND", "operator not found")

    rides_total = body.get("rides_total")
    expires_on = body.get("expires_on")
    if not _is_int(rides_total) or rides_total < 1:
        raise err("ERR_INVALID_REQUEST", "rides_total must be >= 1")
    if not isinstance(expires_on, str):
        raise err("ERR_INVALID_REQUEST", "expires_on is required")
    try:
        parse_date(expires_on)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "expires_on must be YYYY-MM-DD")

    tid = db.new_id()
    rec = {
        "id": tid, "passenger_id": passenger_id, "operator_id": operator_id,
        "rides_total": rides_total, "rides_consumed": 0,
        "rides_remaining": rides_total, "status": "ACTIVE", "expires_on": expires_on,
    }
    db.stamp_create(rec)
    db.travel_passes[tid] = rec
    return success(ser.travel_pass_out(rec), 201)


@bp.route("/v1/passes", methods=["GET"])
def list_passes():
    auth({"Passenger", "SupportAgent"})
    limit, offset = parse_pagination()
    passenger_id = request.args.get("passenger_id")
    operator_id = request.args.get("operator_id")
    recs = []
    for r in db.travel_passes.values():
        if passenger_id is not None and r["passenger_id"] != passenger_id:
            continue
        if operator_id is not None and r["operator_id"] != operator_id:
            continue
        recs.append(r)
    page, meta = paginate(recs, limit, offset)
    return success([ser.travel_pass_out(r) for r in page], 200, pagination=meta)


@bp.route("/v1/passes/<pass_id>", methods=["GET"])
def get_pass(pass_id):
    auth({"Passenger", "SupportAgent"})
    rec = db.travel_passes.get(pass_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "pass not found")
    return success(ser.travel_pass_out(rec), 200)
