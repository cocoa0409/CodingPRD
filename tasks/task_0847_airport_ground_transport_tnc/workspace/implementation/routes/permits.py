from flask import Blueprint, request

import serializers
from common import (
    authenticate, require_role, body_json, as_str, as_int, as_enum,
    parse_dt, must_exist, respond, parse_pagination, list_response,
)
from errors import ApiError
from store import db, base_record, touch, now, new_id

bp = Blueprint("permits", __name__)

PERMIT_ACTIONS = {"ACTIVATE", "RENEW", "EXPIRE", "REVOKE"}
LIVE_PERMIT_STATUSES = {"ISSUED", "ACTIVE", "SUSPENDED"}


@bp.route("/v1/permits", methods=["POST"])
def create_permit():
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority"})
    body = body_json()
    vehicle_id = as_str(body, "vehicle_id")
    avi_tag_id = as_str(body, "avi_tag_id")
    valid_from = parse_dt(body, "valid_from")
    valid_until = parse_dt(body, "valid_until")
    fee_paid_cents = as_int(body, "fee_paid_cents")
    expected_version = as_int(body, "expected_vehicle_version")

    vehicle = must_exist(db.vehicles, vehicle_id)

    # OCC stale-version check runs BEFORE the duplicate-tag check (PRD 3.2 / 2.7).
    if expected_version != vehicle["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_vehicle_version does not match current vehicle version")

    for p in db.permits.values():
        if p["avi_tag_id"] == avi_tag_id and p["permit_status"] in LIVE_PERMIT_STATUSES:
            raise ApiError("ERR_DUPLICATE_AVI_TAG", 409, "avi_tag_id already held by a live permit")

    rec = base_record()
    rec.update({
        "vehicle_id": vehicle_id,
        "avi_tag_id": avi_tag_id,
        "decal_number": None,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "fee_paid_cents": fee_paid_cents,
        "permit_status": "ISSUED",
        "suspended_reason": None,
    })
    db.permits[rec["id"]] = rec
    # Issuance increments the owning vehicle's version by 1 (PRD 3.2 / 2.7).
    touch(vehicle)
    return respond(serializers.permit(rec), "object", 201)


@bp.route("/v1/permits/<permit_id>", methods=["GET"])
def get_permit(permit_id):
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority", "Operator", "CurbCoordinator"})
    p = must_exist(db.permits, permit_id)
    return respond(serializers.permit(p), "object", 200)


@bp.route("/v1/permits", methods=["GET"])
def list_permits():
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority", "Operator", "CurbCoordinator"})
    limit, offset = parse_pagination()
    vehicle_id = request.args.get("vehicle_id")
    items = [p for p in db.permits.values()
             if vehicle_id is None or p["vehicle_id"] == vehicle_id]
    return list_response(items, serializers.permit, limit, offset)


@bp.route("/v1/permits/<permit_id>/transitions", methods=["POST"])
def permit_transition(permit_id):
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority"})
    body = body_json()
    action = as_enum(body, "action", PERMIT_ACTIONS)
    new_valid_until = None
    if action == "RENEW":
        new_valid_until = parse_dt(body, "valid_until")

    p = must_exist(db.permits, permit_id)
    status = p["permit_status"]

    if action == "ACTIVATE":
        if status != "ISSUED":
            raise ApiError("ERR_INVALID_STATE", 409, "Permit not ISSUED")
        if not (p["valid_from"] <= now() < p["valid_until"]):
            raise ApiError("ERR_INVALID_STATE", 409, "Logical clock outside permit validity window")
        p["permit_status"] = "ACTIVE"
        p["decal_number"] = "DECAL-" + new_id()[:12].upper()
        touch(p)
    elif action == "RENEW":
        if status != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Permit not ACTIVE")
        p["valid_until"] = new_valid_until
        touch(p)
    elif action == "EXPIRE":
        if status != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Permit not ACTIVE")
        p["permit_status"] = "EXPIRED"
        touch(p)
    elif action == "REVOKE":
        if status != "ISSUED":
            raise ApiError("ERR_INVALID_STATE", 409, "Permit not ISSUED")
        p["permit_status"] = "REVOKED"
        touch(p)

    return respond(serializers.permit(p), "object", 200)
