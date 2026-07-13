from flask import Blueprint, request

import serializers
from common import (
    authenticate, require_role, body_json, as_str, as_bool,
    must_exist, respond, parse_pagination, list_response,
)
from errors import ApiError
from store import db, base_record

bp = Blueprint("vehicles", __name__)


@bp.route("/v1/vehicles", methods=["POST"])
def create_vehicle():
    uid, role = authenticate()
    require_role(role, {"Operator"})
    body = body_json()
    operator_id = as_str(body, "operator_id")
    plate = as_str(body, "plate")
    is_wav = as_bool(body, "is_wheelchair_accessible", default=False)
    # Ownership: an operator may only register vehicles under its own id (PRD 2.1).
    if operator_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Operator may only act on its own resources")
    must_exist(db.operators, operator_id)

    rec = base_record()
    rec.update({
        "operator_id": operator_id,
        "plate": plate,
        "is_wheelchair_accessible": is_wav,
        "status": "ACTIVE",
    })
    db.vehicles[rec["id"]] = rec
    return respond(serializers.vehicle(rec), "object", 201)


@bp.route("/v1/vehicles/<vehicle_id>", methods=["GET"])
def get_vehicle(vehicle_id):
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority", "Operator", "CurbCoordinator"})
    v = must_exist(db.vehicles, vehicle_id)
    return respond(serializers.vehicle(v), "object", 200)


@bp.route("/v1/vehicles", methods=["GET"])
def list_vehicles():
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority", "Operator", "CurbCoordinator"})
    limit, offset = parse_pagination()
    operator_id = request.args.get("operator_id")
    items = [v for v in db.vehicles.values()
             if operator_id is None or v["operator_id"] == operator_id]
    return list_response(items, serializers.vehicle, limit, offset)
