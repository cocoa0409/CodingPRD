"""Gate registry routes + reverse-FK gate-assignment listing."""
from flask import Blueprint

import db
import errors
import helpers
from middleware import authenticate, require_roles
from response import success, list_success

bp = Blueprint("gates", __name__)

ALL_ROLES = {"OpsAdmin", "GateController", "RampAgent", "SlotCoordinator"}
GATE_STATUSES = {"ACTIVE", "OUT_OF_SERVICE"}


@bp.route("/gates", methods=["POST"])
def create_gate():
    _, role = authenticate()
    require_roles(role, {"OpsAdmin"})
    body = helpers.get_body()
    helpers.require_fields(body, ["code", "terminal", "max_wingspan_m"])

    code = body["code"]
    terminal = body["terminal"]
    if not isinstance(code, str) or not isinstance(terminal, str):
        raise errors.invalid_request("code and terminal must be strings.")
    max_wingspan = helpers.parse_number(body["max_wingspan_m"], "max_wingspan_m", minimum=0)

    is_cute = False
    if body.get("is_cute_equipped") is not None:
        is_cute = helpers.parse_bool(body["is_cute_equipped"], "is_cute_equipped")

    buffer_minutes = 10
    if body.get("buffer_minutes") is not None:
        buffer_minutes = helpers.parse_int(body["buffer_minutes"], "buffer_minutes", minimum=0)

    rec = {
        "id": db.new_id(),
        "code": code,
        "terminal": terminal,
        "max_wingspan_m": max_wingspan,
        "is_cute_equipped": is_cute,
        "buffer_minutes": buffer_minutes,
        "status": "ACTIVE",
        "active_assignment_count": 0,
    }
    db.stamp_create(rec)
    db.gates[rec["id"]] = rec
    return success(helpers.serialize(rec), status=201)


@bp.route("/gates/<gid>", methods=["GET"])
def get_gate(gid):
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = db.gates.get(gid)
    if rec is None:
        raise errors.not_found("Gate not found.")
    return success(helpers.serialize(rec), status=200)


@bp.route("/gates", methods=["GET"])
def list_gates():
    _, role = authenticate()
    require_roles(role, ALL_ROLES)
    from flask import request
    status = request.args.get("status")
    terminal = request.args.get("terminal")
    recs = list(db.gates.values())
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    if terminal is not None:
        recs = [r for r in recs if r["terminal"] == terminal]
    page, limit, offset, total = helpers.paginate(recs)
    return list_success(helpers.serialize_list(page), limit, offset, total)


@bp.route("/gates/<gid>/out-of-service", methods=["POST"])
def out_of_service(gid):
    _, role = authenticate()
    require_roles(role, {"OpsAdmin"})
    rec = db.gates.get(gid)
    if rec is None:
        raise errors.not_found("Gate not found.")
    rec["status"] = "OUT_OF_SERVICE"
    db.touch(rec)
    return success(helpers.serialize(rec), status=200)


@bp.route("/gates/<gid>/gate-assignments", methods=["GET"])
def gate_assignments_for_gate(gid):
    _, role = authenticate()
    require_roles(role, {"OpsAdmin", "GateController", "RampAgent"})
    if gid not in db.gates:
        raise errors.not_found("Gate not found.")
    from flask import request
    status = request.args.get("status")
    recs = [a for a in db.gate_assignments.values() if a.get("gate_id") == gid]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, limit, offset, total = helpers.paginate(recs)
    return list_success(helpers.serialize_list(page), limit, offset, total)
