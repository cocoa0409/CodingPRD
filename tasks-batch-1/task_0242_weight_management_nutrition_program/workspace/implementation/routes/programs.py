"""Program endpoints + deterministic clock (PRD 3.1, 2.4)."""
from flask import Blueprint

from common import (EPOCH_UTC, as_int, as_str, get_body, init_common,
                    parse_pagination, public, require, sort_by_creation)
from db import db
from errors import ERR_INVALID_REQUEST, raise_error
from lookups import get_program, parse_instant, program_clock_seconds
from middleware import require_roles
from response import paginated, success
from serializers import serialize, serialize_list

bp = Blueprint("programs", __name__)

ALL_ROLES = ("ProgramAdmin", "Clinician", "BillingAgent", "Coach", "Member")


@bp.route("/wm/programs", methods=["POST"])
@require_roles("ProgramAdmin")
def create_program():
    body = get_body()
    name = as_str(require(body, "name"), "name")

    description = None
    if body.get("description") is not None:
        description = as_str(body["description"], "description", allow_empty=True)

    cap = 50
    if body.get("coach_max_active_members") is not None:
        cap = as_int(body["coach_max_active_members"], "coach_max_active_members")
        if cap < 0:
            raise_error(ERR_INVALID_REQUEST, "coach_max_active_members must be >= 0")

    program = {
        "name": name,
        "description": description,
        "current_utc": EPOCH_UTC,
        "coach_max_active_members": cap,
    }
    init_common(program)
    db.programs[program["id"]] = program
    return success(serialize(program), 201)


@bp.route("/wm/programs", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_programs():
    limit, offset = parse_pagination()
    items = sort_by_creation(list(db.programs.values()))
    total = len(items)
    page = items[offset:offset + limit]
    return paginated(serialize_list(page), limit, offset, total)


@bp.route("/wm/programs/<program_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_program(program_id):
    program = get_program(program_id)
    return success(serialize(program), 200)


@bp.route("/wm/programs/<program_id>/clock-set", methods=["POST"])
@require_roles("ProgramAdmin")
def clock_set(program_id):
    program = get_program(program_id)
    body = get_body()
    target = require(body, "to_iso8601")
    new_secs = parse_instant(target, "to_iso8601")
    current_secs = program_clock_seconds(program)
    if new_secs < current_secs:
        raise_error(ERR_INVALID_REQUEST,
                    "to_iso8601 must not predate current_utc")
    program["current_utc"] = target
    from common import touch
    touch(program)
    return success(serialize(program), 200)
