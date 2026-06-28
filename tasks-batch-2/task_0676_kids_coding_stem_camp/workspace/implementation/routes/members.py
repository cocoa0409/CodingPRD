"""Member routes: create, fetch, list, progress, promote (PRD §3.2, §3.7)."""
from flask import Blueprint

import errors
from errors import err
from db import db
from response import success
from serialize import out
from middleware import get_auth, require_role
from validators import get_body, require_str, parse_datetime, parse_pagination
from services import lookup
from services.member_service import recompute_active_badge_count
from services.pricing import member_progress
from routes.common import arg, paginate

bp = Blueprint("members", __name__)


def _rank1_belt(program_id):
    for b in db.belt_levels.values():
        if b["program_id"] == program_id and b["rank"] == 1:
            return b
    return None


@bp.route("/members", methods=["POST"])
def create_member():
    user_id, role = get_auth()
    require_role(role, {"CenterAdmin", "Guardian"})
    body = get_body()
    guardian_id = body.get("guardian_id")
    # ownership (priority 3) before existence per global ordering; but the guardian
    # being acted upon must exist to compare. We perform owner check on the
    # supplied guardian_id, then existence of all referenced resources.
    lookup.check_owner(role, user_id, guardian_id)
    lookup.require_guardian(guardian_id)
    program_id = body.get("program_id")
    lookup.require_program(program_id)

    full_name = require_str(body, "full_name")
    birth_date = parse_datetime(body, "birth_date")  # validates ISO shape
    rank1 = _rank1_belt(program_id)
    if rank1 is None:
        # No belt ladder configured for the program; cannot initialize belt.
        raise err(errors.ERR_INVALID_FIELD, "Program has no rank-1 belt level.")
    rec = db.make({
        "guardian_id": guardian_id,
        "program_id": program_id,
        "full_name": full_name,
        "birth_date": body["birth_date"],
        "current_belt_level_id": rank1["id"],
        "active_badge_count": 0,
    })
    db.members[rec["id"]] = rec
    return success(out(rec), status=201)


@bp.route("/members/<rid>", methods=["GET"])
def get_member(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    rec = lookup.require_member(rid)
    return success(out(rec))


@bp.route("/members", methods=["GET"])
def list_members():
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    limit, offset = parse_pagination()
    guardian_id = arg("guardian_id")
    program_id = arg("program_id")
    belt_id = arg("current_belt_level_id")
    items = [m for m in db.members.values()
             if (guardian_id is None or m["guardian_id"] == guardian_id)
             and (program_id is None or m["program_id"] == program_id)
             and (belt_id is None or m["current_belt_level_id"] == belt_id)]
    return paginate(items, limit, offset)


@bp.route("/members/<rid>/progress", methods=["GET"])
def member_progress_read(rid):
    user_id, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    member = lookup.require_member(rid)
    lookup.check_owner(role, user_id, lookup.member_guardian_id(member))
    # Persist a reconciliation of active_badge_count if stale.
    if recompute_active_badge_count(member):
        db.touch(member)
    breakdown = member_progress(member)
    data = out(member)
    data["progress"] = breakdown
    return success(data)


@bp.route("/members/<rid>/promote", methods=["POST"])
def promote_member(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor"})
    member = lookup.require_member(rid)
    current_belt = db.belt_levels[member["current_belt_level_id"]]
    program_id = member["program_id"]
    # next belt = rank+1 belt in member's program
    next_belt = None
    for b in db.belt_levels.values():
        if b["program_id"] == program_id and b["rank"] == current_belt["rank"] + 1:
            next_belt = b
            break
    if next_belt is None:
        raise err(errors.ERR_PROMOTION_REQUIREMENTS_NOT_MET, "No next belt exists.")
    # must currently hold the prerequisite belt of the next belt (rank order).
    if next_belt["prereq_belt_level_id"] is not None and \
            next_belt["prereq_belt_level_id"] != member["current_belt_level_id"]:
        raise err(errors.ERR_PROMOTION_REQUIREMENTS_NOT_MET, "Prerequisite belt not held.")
    # active_badge_count for current belt must meet current belt's requirement.
    recompute_active_badge_count(member)
    if member["active_badge_count"] < current_belt["required_badge_count"]:
        raise err(errors.ERR_PROMOTION_REQUIREMENTS_NOT_MET, "Insufficient active badges.")
    member["current_belt_level_id"] = next_belt["id"]
    recompute_active_badge_count(member)  # reset relative to new belt
    db.touch(member)
    return success(out(member))
