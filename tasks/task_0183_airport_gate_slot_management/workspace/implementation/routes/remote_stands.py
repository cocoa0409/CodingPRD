"""RemoteStand registry routes + reverse-FK gate-assignment listing."""
from flask import Blueprint, request

import db
import errors
import helpers
from middleware import authenticate, require_roles
from response import success, list_success

bp = Blueprint("remote_stands", __name__)

ALL_ROLES = {"OpsAdmin", "GateController", "RampAgent", "SlotCoordinator"}


@bp.route("/remote-stands", methods=["POST"])
def create_remote_stand():
    _, role = authenticate()
    require_roles(role, {"OpsAdmin"})
    body = helpers.get_body()
    helpers.require_fields(body, ["code", "max_wingspan_m"])

    code = body["code"]
    if not isinstance(code, str):
        raise errors.invalid_request("code must be a string.")
    max_wingspan = helpers.parse_number(body["max_wingspan_m"], "max_wingspan_m", minimum=0)

    capacity = 1
    if body.get("capacity") is not None:
        capacity = helpers.parse_int(body["capacity"], "capacity", minimum=1)

    rec = {
        "id": db.new_id(),
        "code": code,
        "max_wingspan_m": max_wingspan,
        "capacity": capacity,
        "status": "ACTIVE",
        "occupancy_count": 0,
    }
    db.stamp_create(rec)
    db.remote_stands[rec["id"]] = rec
    return success(helpers.serialize(rec), status=201)


@bp.route("/remote-stands/<sid>", methods=["GET"])
def get_remote_stand(sid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = db.remote_stands.get(sid)
    if rec is None:
        raise errors.not_found("Remote stand not found.")
    return success(helpers.serialize(rec), status=200)


@bp.route("/remote-stands", methods=["GET"])
def list_remote_stands():
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    status = request.args.get("status")
    recs = list(db.remote_stands.values())
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, limit, offset, total = helpers.paginate(recs)
    return list_success(helpers.serialize_list(page), limit, offset, total)


@bp.route("/remote-stands/<sid>/gate-assignments", methods=["GET"])
def gate_assignments_for_remote(sid):
    _, role = authenticate()
    require_roles(role, {"OpsAdmin", "GateController", "RampAgent"})
    if sid not in db.remote_stands:
        raise errors.not_found("Remote stand not found.")
    status = request.args.get("status")
    # rows whose remote_stand_id is this stand OR whose tow_target_stand_id is this stand
    recs = [a for a in db.gate_assignments.values()
            if a.get("remote_stand_id") == sid or a.get("tow_target_stand_id") == sid]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, limit, offset, total = helpers.paginate(recs)
    return list_success(helpers.serialize_list(page), limit, offset, total)
