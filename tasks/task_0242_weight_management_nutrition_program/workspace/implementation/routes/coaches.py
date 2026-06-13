"""Coach endpoints (PRD 3.2)."""
from flask import Blueprint, g, request

from common import (as_bool, as_enum, as_str, get_body, init_common,
                    parse_pagination, require, sort_by_creation, touch)
from db import db
from errors import ERR_DUPLICATE_EMAIL, raise_error
from lookups import get_coach, get_program
from middleware import require_roles
from response import paginated, success
from serializers import serialize, serialize_list

bp = Blueprint("coaches", __name__)

ALL_ROLES = ("ProgramAdmin", "Clinician", "BillingAgent", "Coach", "Member")
SPECIALTIES = {"GENERAL", "DIETITIAN", "CLINICAL"}


@bp.route("/wm/coaches", methods=["POST"])
@require_roles("ProgramAdmin")
def create_coach():
    body = get_body()
    program_id = as_str(require(body, "program_id"), "program_id")
    get_program(program_id)

    full_name = as_str(require(body, "full_name"), "full_name")
    email = as_str(require(body, "email"), "email")

    specialty = "GENERAL"
    if body.get("specialty") is not None:
        specialty = as_enum(body["specialty"], "specialty", SPECIALTIES)

    accepting = True
    if body.get("accepting") is not None:
        accepting = as_bool(body["accepting"], "accepting")

    for c in db.coaches.values():
        if c["program_id"] == program_id and c["email"].lower() == email.lower():
            raise_error(ERR_DUPLICATE_EMAIL, "Email already used within program")

    coach = {
        "program_id": program_id,
        "full_name": full_name,
        "email": email,
        "specialty": specialty,
        "active_member_count": 0,
        "accepting": accepting,
    }
    init_common(coach)
    db.coaches[coach["id"]] = coach
    return success(serialize(coach), 201)


@bp.route("/wm/coaches", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_coaches():
    limit, offset = parse_pagination()
    items = list(db.coaches.values())
    program_id = request.args.get("program_id")
    if program_id is not None:
        items = [c for c in items if c["program_id"] == program_id]
    items = sort_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return paginated(serialize_list(page), limit, offset, total)


@bp.route("/wm/coaches/<coach_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_coach(coach_id):
    return success(serialize(get_coach(coach_id)), 200)


@bp.route("/wm/coaches/<coach_id>", methods=["PATCH"])
@require_roles("ProgramAdmin", "Coach")
def update_coach(coach_id):
    coach = get_coach(coach_id)
    body = get_body()
    changed = False
    if "accepting" in body and body["accepting"] is not None:
        coach["accepting"] = as_bool(body["accepting"], "accepting")
        changed = True
    if "specialty" in body and body["specialty"] is not None:
        coach["specialty"] = as_enum(body["specialty"], "specialty", SPECIALTIES)
        changed = True
    if changed:
        touch(coach)
    return success(serialize(coach), 200)
