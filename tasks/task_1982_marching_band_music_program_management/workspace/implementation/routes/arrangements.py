"""MusicArrangement endpoints."""
from flask import Blueprint, request
from db import store, new_id, now, now_iso, parse_dt
from errors import (
    raise_err, ERR_ARRANGEMENT_NOT_FOUND, ERR_ARRANGEMENT_NOT_QUOTED,
    ERR_ARRANGEMENT_NOT_APPROVED, ERR_SEGREGATION_OF_DUTIES,
    ERR_MUSIC_BUDGET_EXCEEDED, ERR_LICENSE_WINDOW_INVALID, ERR_INVALID_REQUEST,
)
from middleware import require_roles
from response import success, parse_pagination, paginate
from services.serializers import arrangement_out
from services.validators import body, require, check_unknown, to_int, to_str, to_enum
from services.clock_eval import apply_time_transitions
from routes.programs import _get_program_or_404, _program_posture_open

bp = Blueprint("arrangements", __name__)

LICENSE_TYPES = {"STANDARD", "CUSTOM_ARRANGEMENT", "COMPETITION_EXCERPT"}


def _get_arrangement_or_404(aid):
    a = store.arrangements.get(aid)
    if a is None:
        raise_err(ERR_ARRANGEMENT_NOT_FOUND, f"arrangement {aid} not found")
    return a


@bp.route("/band/arrangements", methods=["POST"])
def create_arrangement():
    uid, role = require_roles(["BandDirector", "AssistantDirector", "SectionLeader"])
    data = body()
    check_unknown(data, {"program_id", "title", "arranger", "license_type",
                         "cost_cents", "rights_end"})
    require(data, "program_id", "title", "arranger", "license_type", "cost_cents", "rights_end")
    pid = to_str(data["program_id"], "program_id")
    title = to_str(data["title"], "title")
    arranger = to_str(data["arranger"], "arranger")
    license_type = to_enum(data["license_type"], "license_type", LICENSE_TYPES)
    cost_cents = to_int(data["cost_cents"], "cost_cents")
    try:
        rights_end = parse_dt(data["rights_end"])
    except (ValueError, TypeError):
        raise_err(ERR_INVALID_REQUEST, "rights_end must be ISO8601")

    program = _get_program_or_404(pid)
    _program_posture_open(program)

    # rights_end must be in future
    if rights_end <= now():
        raise_err(ERR_LICENSE_WINDOW_INVALID, "rights_end must be in the future")

    aid = new_id()
    now_s = now_iso()
    a = {
        "id": aid,
        "program_id": pid,
        "title": title,
        "arranger": arranger,
        "license_type": license_type,
        "cost_cents": cost_cents,
        "rights_end": rights_end,
        "status": "QUOTED",
        "creator_user_id": uid,
        "approver_user_id": None,
        "created_at": now_s,
        "updated_at": now_s,
        "version": 1,
    }
    store.arrangements[aid] = a
    return success(arrangement_out(a), status=201)


@bp.route("/band/arrangements", methods=["GET"])
def list_arrangements():
    require_roles(["Any"])
    apply_time_transitions()
    limit, offset = parse_pagination(request.args)
    items = list(store.arrangements.values())
    pid = request.args.get("program_id")
    if pid:
        items = [a for a in items if a["program_id"] == pid]
    st = request.args.get("status")
    if st:
        items = [a for a in items if a["status"] == st]
    items.sort(key=lambda x: x["created_at"])
    page, pag = paginate(items, limit, offset)
    return success([arrangement_out(a) for a in page], is_list=True, pagination=pag)


@bp.route("/band/arrangements/<aid>", methods=["GET"])
def get_arrangement(aid):
    require_roles(["Any"])
    apply_time_transitions()
    a = _get_arrangement_or_404(aid)
    return success(arrangement_out(a))


@bp.route("/band/arrangements/<aid>/approve", methods=["POST"])
def approve_arrangement(aid):
    uid, role = require_roles(["BandDirector"])
    a = _get_arrangement_or_404(aid)
    if a["status"] != "QUOTED":
        raise_err(ERR_ARRANGEMENT_NOT_QUOTED, "arrangement is not QUOTED")
    if uid == a["creator_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "approver must differ from creator")
    a["status"] = "APPROVED"
    a["approver_user_id"] = uid
    a["version"] += 1
    a["updated_at"] = now_iso()
    return success(arrangement_out(a))


@bp.route("/band/arrangements/<aid>/reject", methods=["POST"])
def reject_arrangement(aid):
    uid, role = require_roles(["BandDirector"])
    a = _get_arrangement_or_404(aid)
    if a["status"] != "QUOTED":
        raise_err(ERR_ARRANGEMENT_NOT_QUOTED, "arrangement is not QUOTED")
    if uid == a["creator_user_id"]:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "rejecter must differ from creator")
    a["status"] = "REJECTED"
    a["version"] += 1
    a["updated_at"] = now_iso()
    return success(arrangement_out(a))


@bp.route("/band/arrangements/<aid>/purchase", methods=["POST"])
def purchase_arrangement(aid):
    require_roles(["BoosterTreasurer"])
    a = _get_arrangement_or_404(aid)
    if a["status"] != "APPROVED":
        raise_err(ERR_ARRANGEMENT_NOT_APPROVED, "arrangement is not APPROVED")
    program = _get_program_or_404(a["program_id"])
    if program["music_spent_cents"] + a["cost_cents"] > program["music_budget_cents"]:
        raise_err(ERR_MUSIC_BUDGET_EXCEEDED, "purchase would exceed music budget")
    program["music_spent_cents"] += a["cost_cents"]
    program["version"] += 1
    program["updated_at"] = now_iso()
    a["status"] = "LICENSED_ACTIVE"
    a["version"] += 1
    a["updated_at"] = now_iso()
    return success(arrangement_out(a))
