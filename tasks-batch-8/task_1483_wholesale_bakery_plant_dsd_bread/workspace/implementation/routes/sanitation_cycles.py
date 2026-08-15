"""SanitationCycle endpoints."""

from flask import Blueprint, request

from db import DB
from middleware import get_auth, require_role
from helpers import (
    body, req_string, req_enum, make_entity, touch, lookup, list_response, public,
)
from response import success_object
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_SANITATION_NOT_COMPLETE, ERR_SEGREGATION_OF_DUTIES,
    ERR_NOT_FOUND,
)
from services.calculations import sanitation_required_minutes, parse_iso_z

bp = Blueprint("sanitation_cycles", __name__)

ALLERGEN_CLASSES = {"NONE", "SESAME", "TREE_NUT", "PEANUT"}


@bp.route("/bakery/sanitation-cycles", methods=["POST"])
def create_cycle():
    _, role = get_auth()
    require_role(role, {"LineOperator"})
    data = body()
    line_id = req_string(data, "line_id")
    line = lookup(DB.lines, line_id, "line")
    to_class = req_enum(data, "to_allergen_class", ALLERGEN_CLASSES)
    from_class = line.get("allergen_class_current", "NONE")
    required = sanitation_required_minutes(from_class, to_class)
    cycle = make_entity({
        "line_id": line_id,
        "from_allergen_class": from_class,
        "to_allergen_class": to_class,
        "required_minutes": required,
        "status": "REQUESTED",
        "started_at": None,
        "started_by_user_id": None,
        "verified_at": None,
    })
    DB.sanitation_cycles[cycle["id"]] = cycle
    return success_object(public(cycle), status=201)


@bp.route("/bakery/sanitation-cycles/<cid>", methods=["GET"])
def get_cycle(cid):
    get_auth()
    cycle = lookup(DB.sanitation_cycles, cid, "sanitation cycle")
    return success_object(public(cycle))


@bp.route("/bakery/sanitation-cycles", methods=["GET"])
def list_cycles():
    get_auth()
    filters = {
        "line_id": request.args.get("line_id"),
        "status": request.args.get("status"),
    }
    return list_response(list(DB.sanitation_cycles.values()), filters)


@bp.route("/bakery/sanitation-cycles/<cid>/start", methods=["POST"])
def start_cycle(cid):
    user_id, role = get_auth()
    require_role(role, {"LineOperator"})
    cycle = lookup(DB.sanitation_cycles, cid, "sanitation cycle")
    if cycle.get("status") not in ("REQUESTED", "FAILED"):
        raise ApiError(ERR_INVALID_STATE, "Cycle is not REQUESTED or FAILED", 409)
    line = DB.lines.get(cycle["line_id"])
    if line is None:
        raise ApiError(ERR_NOT_FOUND, "line not found", 404)
    cycle["status"] = "IN_PROGRESS"
    cycle["started_at"] = DB.clock_iso()
    cycle["started_by_user_id"] = user_id
    touch(cycle)
    line["cleanliness"] = "SANITIZING"
    touch(line)
    return success_object(public(cycle))


@bp.route("/bakery/sanitation-cycles/<cid>/verify", methods=["POST"])
def verify_cycle(cid):
    user_id, role = get_auth()
    require_role(role, {"QALead"})
    cycle = lookup(DB.sanitation_cycles, cid, "sanitation cycle")
    if cycle.get("status") != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, "Cycle is not IN_PROGRESS", 409)
    if user_id == cycle.get("started_by_user_id"):
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Verifier must differ from starter", 403)
    started_dt = parse_iso_z(cycle["started_at"])
    elapsed_min = (DB.clock - started_dt).total_seconds() / 60.0
    if elapsed_min < int(cycle["required_minutes"]):
        raise ApiError(ERR_SANITATION_NOT_COMPLETE, "Required minutes have not elapsed", 409)
    line = DB.lines.get(cycle["line_id"])
    if line is None:
        raise ApiError(ERR_NOT_FOUND, "line not found", 404)
    cycle["status"] = "VERIFIED"
    cycle["verified_at"] = DB.clock_iso()
    touch(cycle)
    line["cleanliness"] = "CLEAN"
    line["allergen_class_current"] = cycle["to_allergen_class"]
    touch(line)
    return success_object(public(cycle))


@bp.route("/bakery/sanitation-cycles/<cid>/fail", methods=["POST"])
def fail_cycle(cid):
    _, role = get_auth()
    require_role(role, {"QALead"})
    cycle = lookup(DB.sanitation_cycles, cid, "sanitation cycle")
    if cycle.get("status") != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, "Cycle is not IN_PROGRESS", 409)
    line = DB.lines.get(cycle["line_id"])
    if line is None:
        raise ApiError(ERR_NOT_FOUND, "line not found", 404)
    cycle["status"] = "FAILED"
    touch(cycle)
    line["cleanliness"] = "DIRTY"
    touch(line)
    return success_object(public(cycle))
