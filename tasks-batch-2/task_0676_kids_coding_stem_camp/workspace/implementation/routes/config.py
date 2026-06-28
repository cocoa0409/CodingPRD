"""Configuration routes: Center, Program, BeltLevel, Badge (PRD §3.1)."""
import re

from flask import Blueprint

import errors
from errors import err
from db import db
from response import success
from serialize import out
from middleware import get_auth, require_role
from validators import (
    get_body, require_str, require_int, optional_int, require_enum,
    parse_pagination,
)
from services import lookup
from services.member_service import recompute_active_badge_count
from routes.common import arg, paginate

bp = Blueprint("config", __name__)

CODE_RE = re.compile(r"^[A-Z0-9]{2,8}$")


# ---- Center -----------------------------------------------------------------
@bp.route("/centers", methods=["POST"])
def create_center():
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    body = get_body()
    name = require_str(body, "name")
    device_count = require_int(body, "device_count", minimum=1)
    ratio = require_int(body, "min_student_instructor_ratio", minimum=1)
    timezone = body.get("timezone", "UTC")
    if timezone is None:
        timezone = "UTC"
    if not isinstance(timezone, str) or timezone == "":
        raise err(errors.ERR_INVALID_FIELD, "timezone must be a non-empty string.")
    rec = db.make({
        "name": name,
        "device_count": device_count,
        "min_student_instructor_ratio": ratio,
        "timezone": timezone,
    })
    db.centers[rec["id"]] = rec
    return success(out(rec), status=201)


@bp.route("/centers/<rid>", methods=["GET"])
def get_center(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    rec = lookup.require_center(rid)
    return success(out(rec))


# ---- Program ----------------------------------------------------------------
@bp.route("/programs", methods=["POST"])
def create_program():
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    body = get_body()
    name = require_str(body, "name")
    code = require_str(body, "code")
    if not CODE_RE.match(code):
        raise err(errors.ERR_INVALID_FIELD, "code must be 2-8 uppercase A-Z0-9 chars.")
    for existing in db.programs.values():
        if existing["code"] == code:
            raise err(errors.ERR_INVALID_FIELD, "code must be unique.")
    min_age = require_int(body, "min_age", minimum=4)
    max_age = require_int(body, "max_age")
    if max_age < min_age:
        raise err(errors.ERR_INVALID_FIELD, "max_age must be >= min_age.")
    fee = require_int(body, "drop_in_fee_cents", minimum=0)
    rec = db.make({
        "name": name,
        "code": code,
        "min_age": min_age,
        "max_age": max_age,
        "drop_in_fee_cents": fee,
    })
    db.programs[rec["id"]] = rec
    return success(out(rec), status=201)


@bp.route("/programs/<rid>", methods=["GET"])
def get_program(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    rec = lookup.require_program(rid)
    return success(out(rec))


# ---- BeltLevel --------------------------------------------------------------
@bp.route("/belt-levels", methods=["POST"])
def create_belt_level():
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    body = get_body()
    # Existence (priority 4) before deep field validation.
    program_id = body.get("program_id")
    lookup.require_program(program_id)
    prereq_id = body.get("prereq_belt_level_id")
    if prereq_id is not None:
        lookup.require_belt_level(prereq_id)

    name = require_str(body, "name")
    rank = require_int(body, "rank", minimum=1)
    required_badge_count = require_int(body, "required_badge_count", minimum=0)
    # rank unique per program
    for b in db.belt_levels.values():
        if b["program_id"] == program_id and b["rank"] == rank:
            raise err(errors.ERR_INVALID_FIELD, "rank must be unique per program.")
    # prereq null only for rank 1
    if rank == 1:
        if prereq_id is not None:
            raise err(errors.ERR_INVALID_FIELD, "prereq_belt_level_id must be null for rank 1.")
    else:
        if prereq_id is None:
            raise err(errors.ERR_INVALID_FIELD, "prereq_belt_level_id is required for rank > 1.")
    rec = db.make({
        "program_id": program_id,
        "name": name,
        "rank": rank,
        "prereq_belt_level_id": prereq_id,
        "required_badge_count": required_badge_count,
    })
    db.belt_levels[rec["id"]] = rec
    return success(out(rec), status=201)


@bp.route("/belt-levels/<rid>", methods=["GET"])
def get_belt_level(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    rec = lookup.require_belt_level(rid)
    return success(out(rec))


@bp.route("/belt-levels", methods=["GET"])
def list_belt_levels():
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    limit, offset = parse_pagination()
    program_id = arg("program_id")
    prereq_id = arg("prereq_belt_level_id")
    items = [b for b in db.belt_levels.values()
             if (program_id is None or b["program_id"] == program_id)
             and (prereq_id is None or b["prereq_belt_level_id"] == prereq_id)]
    return paginate(items, limit, offset)


# ---- Badge ------------------------------------------------------------------
@bp.route("/badges", methods=["POST"])
def create_badge():
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    body = get_body()
    belt_level_id = body.get("belt_level_id")
    lookup.require_belt_level(belt_level_id)
    name = require_str(body, "name")
    rec = db.make({
        "belt_level_id": belt_level_id,
        "name": name,
        "status": "ACTIVE",
    })
    db.badges[rec["id"]] = rec
    return success(out(rec), status=201)


@bp.route("/badges/<rid>", methods=["GET"])
def get_badge(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    rec = lookup.require_badge(rid)
    return success(out(rec))


@bp.route("/badges", methods=["GET"])
def list_badges():
    _, role = get_auth()
    require_role(role, {"CenterAdmin", "Instructor", "Guardian"})
    limit, offset = parse_pagination()
    belt_level_id = arg("belt_level_id")
    items = [b for b in db.badges.values()
             if belt_level_id is None or b["belt_level_id"] == belt_level_id]
    return paginate(items, limit, offset)


@bp.route("/badges/<rid>/retire", methods=["POST"])
def retire_badge(rid):
    _, role = get_auth()
    require_role(role, {"CenterAdmin"})
    badge = lookup.require_badge(rid)
    # No state-machine transition table for Badge beyond ACTIVE->RETIRED; treat
    # an already-RETIRED badge as an invalid-state transition.
    if badge["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "Badge is not ACTIVE.")
    badge["status"] = "RETIRED"
    db.touch(badge)
    # Cascade: recompute active_badge_count for every member who holds an ACTIVE
    # award of this badge on their current belt.
    affected_members = set()
    for award in db.badge_awards.values():
        if award["status"] != "ACTIVE" or award["badge_id"] != badge["id"]:
            continue
        enrollment = db.enrollments.get(award["enrollment_id"])
        if enrollment is None:
            continue
        member = db.members.get(enrollment["member_id"])
        if member is None:
            continue
        if badge["belt_level_id"] == member["current_belt_level_id"]:
            affected_members.add(member["id"])
    for mid in affected_members:
        member = db.members[mid]
        if recompute_active_badge_count(member):
            db.touch(member)
    return success(out(badge))
