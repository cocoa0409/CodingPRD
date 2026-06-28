"""LashTech + SanitationLog routes (PRD §3.2)."""
from flask import Blueprint, request

from common import (bad_request, get_json_body, parse_pagination, paginate,
                    require_int, require_str, sort_by_created, stamp_create, touch)
from db import store
from lookups import get_tech_or_404, parse_dt_or_400
from middleware import get_user_context, require_role
from response import success_list, success_object
from services import derive
import serialize

bp = Blueprint("techs", __name__)

READ_ROLES = {"StudioManager", "FrontDesk", "LashTech", "Member"}


@bp.route("/lash-techs", methods=["POST"])
def create_lash_tech():
    _, role = get_user_context()
    require_role(role, {"StudioManager"})
    body = get_json_body()
    studio_id = require_str(body, "studio_id")
    from lookups import get_studio_or_404
    studio = get_studio_or_404(studio_id)
    full_name = require_str(body, "full_name")
    skill_level = require_int(body, "skill_level")
    if not (1 <= skill_level <= 3):
        raise bad_request("skill_level must be between 1 and 3 inclusive.")
    station_number = require_int(body, "station_number")
    if station_number < 1:
        raise bad_request("station_number must be at least 1.")

    rec = {
        "studio_id": studio["id"],
        "full_name": full_name,
        "skill_level": skill_level,
        "station_number": station_number,
        "status": "AVAILABLE",
    }
    stamp_create(rec)
    store.lash_techs[rec["id"]] = rec
    return success_object(serialize.lash_tech_out(rec), status=201)


@bp.route("/lash-techs", methods=["GET"])
def list_lash_techs():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    studio_id = request.args.get("studio_id")
    items = list(store.lash_techs.values())
    if studio_id is not None:
        items = [t for t in items if t["studio_id"] == studio_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize.lash_tech_out(t) for t in page], limit, offset, total)


@bp.route("/lash-techs/<tid>", methods=["GET"])
def get_lash_tech(tid):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    t = get_tech_or_404(tid)
    return success_object(serialize.lash_tech_out(t))


@bp.route("/lash-techs/<tid>/set-status", methods=["POST"])
def set_tech_status(tid):
    _, role = get_user_context()
    require_role(role, {"StudioManager"})
    t = get_tech_or_404(tid)
    body = get_json_body()
    status = body.get("status")
    if status not in ("AVAILABLE", "OFF_DUTY"):
        raise bad_request("status must be AVAILABLE or OFF_DUTY.")
    t["status"] = status
    touch(t)
    return success_object(serialize.lash_tech_out(t))


@bp.route("/lash-techs/<tid>/sanitation-logs", methods=["GET"])
def list_tech_sanitation_logs(tid):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    t = get_tech_or_404(tid)
    limit, offset = parse_pagination()
    items = [s for s in store.sanitation_logs.values() if s["lash_tech_id"] == t["id"]]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize.sanitation_log_out(s) for s in page], limit, offset, total)


# --------------------------- SanitationLog ---------------------------------
@bp.route("/sanitation-logs", methods=["POST"])
def create_sanitation_log():
    user_id, role = get_user_context()
    require_role(role, {"StudioManager", "FrontDesk", "LashTech"})
    body = get_json_body()
    lash_tech_id = require_str(body, "lash_tech_id")
    tech = get_tech_or_404(lash_tech_id)
    # LashTech may only record sanitation for own station (ownership, PRD §2.1).
    if role == "LashTech" and user_id != tech["id"]:
        from errors import ApiError, ERR_FORBIDDEN_ROLE
        raise ApiError(ERR_FORBIDDEN_ROLE, 403, "Technicians may only act on their own station.")
    sanitized_at = parse_dt_or_400(body, "sanitized_at_utc")

    rec = {
        "lash_tech_id": tech["id"],
        "performed_by_user_id": user_id,
        "sanitized_at_utc": sanitized_at,
        "valid_through_utc": derive.sanitation_valid_through(sanitized_at),
        "status": "COMPLETED",
    }
    stamp_create(rec)
    store.sanitation_logs[rec["id"]] = rec
    # tech.station_sanitized_through_utc recomputed (derived at read; recompute
    # is a mutation of the tech parent -> bump version/updated_at, PRD §2.5).
    touch(tech)
    return success_object(serialize.sanitation_log_out(rec), status=201)


@bp.route("/sanitation-logs", methods=["GET"])
def list_sanitation_logs():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    lash_tech_id = request.args.get("lash_tech_id")
    items = list(store.sanitation_logs.values())
    if lash_tech_id is not None:
        items = [s for s in items if s["lash_tech_id"] == lash_tech_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize.sanitation_log_out(s) for s in page], limit, offset, total)


@bp.route("/sanitation-logs/<sid>", methods=["GET"])
def get_sanitation_log(sid):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    s = store.sanitation_logs.get(sid)
    if not s:
        from errors import ApiError, ERR_TECH_NOT_FOUND
        raise ApiError(ERR_TECH_NOT_FOUND, 404, "Sanitation log not found.")
    return success_object(serialize.sanitation_log_out(s))


@bp.route("/sanitation-logs/<sid>/void", methods=["POST"])
def void_sanitation_log(sid):
    _, role = get_user_context()
    require_role(role, {"StudioManager"})
    s = store.sanitation_logs.get(sid)
    if not s:
        from errors import ApiError, ERR_TECH_NOT_FOUND
        raise ApiError(ERR_TECH_NOT_FOUND, 404, "Sanitation log not found.")
    s["status"] = "VOIDED"
    touch(s)
    # Recompute tech.station_sanitized_through_utc excluding voided.
    tech = store.lash_techs.get(s["lash_tech_id"])
    if tech:
        touch(tech)
    return success_object(serialize.sanitation_log_out(s))
