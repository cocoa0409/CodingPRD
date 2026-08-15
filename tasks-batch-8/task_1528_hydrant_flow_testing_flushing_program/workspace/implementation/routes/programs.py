"""FlushingProgram endpoints: create, get, close, sweep."""
from flask import Blueprint

import db
from db import new_base, touch
from errors import (
    ApiError,
    ERR_PROGRAM_ALREADY_EXISTS,
    ERR_PROGRAM_NOT_FOUND,
    ERR_PROGRAM_NOT_OPEN,
    not_found,
)
from middleware import auth, require_role
from response import success_object
from serializers import program_view
from services import compute_inspection_tier, program_hydrants
from validation import F, validate_body, validate_empty_body

bp = Blueprint("programs", __name__)


def get_program_or_404(program_id):
    p = db.store.programs.get(program_id)
    if p is None:
        raise not_found(ERR_PROGRAM_NOT_FOUND, "FlushingProgram")
    return p


@bp.post("/programs")
def create_program():
    auth_user, role = auth()
    body = validate_body([
        F("program_year", "int"),
        F("season", "enum", arg={"SPRING", "FALL"}),
    ])
    require_role(role, {"ProgramAdmin"})
    for p in db.store.programs.values():
        if p["program_year"] == body["program_year"] and p["season"] == body["season"]:
            raise ApiError(
                ERR_PROGRAM_ALREADY_EXISTS,
                "A program with this (program_year, season) already exists",
                409,
            )
    program = new_base()
    program.update({
        "program_year": body["program_year"],
        "season": body["season"],
        "status": "OPEN",
        "hydrants_out_of_service_count": 0,
        "unacknowledged_notification_count": 0,
    })
    db.store.programs[program["id"]] = program
    return success_object(program_view(program), code=201)


@bp.get("/programs/<program_id>")
def get_program(program_id):
    from middleware import auth_any
    auth_any()
    return success_object(program_view(get_program_or_404(program_id)))


@bp.post("/programs/<program_id>/close")
def close_program(program_id):
    auth_user, role = auth()
    validate_empty_body()
    require_role(role, {"ProgramAdmin"})
    program = get_program_or_404(program_id)
    if program["status"] != "OPEN":
        raise ApiError(ERR_PROGRAM_NOT_OPEN, "Program must be OPEN", 409)
    program["status"] = "CLOSED"
    touch(program)
    return success_object(program_view(program))


@bp.post("/programs/<program_id>/sweep")
def sweep_program(program_id):
    auth_user, role = auth()
    validate_empty_body()
    require_role(role, {"ProgramAdmin"})
    program = get_program_or_404(program_id)
    now = db.now()

    tier_count = 0
    hydrants = program_hydrants(program["id"])
    hydrant_ids = {h["id"] for h in hydrants}
    for h in hydrants:
        # inspection_due_tier recomputed for every hydrant of the program
        new_tier = compute_inspection_tier(h)
        tier_count += 1
        if new_tier != h["inspection_tier"]:
            h["inspection_tier"] = new_tier
            touch(h)

    missed = 0
    for t in db.store.flow_tests.values():
        if t["hydrant_id"] in hydrant_ids and t["status"] == "SCHEDULED" and t["window_end"] < now:
            t["status"] = "MISSED"
            touch(t)
            missed += 1

    escalated = 0
    for o in db.store.outages.values():
        if (
            o["hydrant_id"] in hydrant_ids
            and o["status"] == "ACTIVE"
            and o["notification_status"] == "PENDING"
            and now > o["ack_deadline"]
            and not o["escalated"]
        ):
            o["escalated"] = True
            touch(o)
            escalated += 1

    return success_object({
        "missed_flow_tests": missed,
        "escalated_outages": escalated,
        "tier_recomputed_hydrants": tier_count,
    })
