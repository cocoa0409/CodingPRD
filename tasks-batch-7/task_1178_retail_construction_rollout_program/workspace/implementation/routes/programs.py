"""RolloutProgram endpoints (§3.1)."""
from flask import Blueprint

from db import store
from errors import ApiError
from middleware import ALL_ROLES, authed
from response import ok
from routes import list_response, require_state
from util import bump, new_entity, serialize
from validate import get_or_404, json_body, req_int, req_str

bp = Blueprint("programs", __name__)

TERMINAL = ("COMPLETE",)


@bp.route("/rollout/programs", methods=["POST"], strict_slashes=False)
@authed(["ProgramDirector"])
def create_program():
    body = json_body()
    name = req_str(body, "name")
    fiscal_year = req_int(body, "fiscal_year")
    total_budget = req_int(body, "total_budget_cents")
    pool = req_int(body, "contingency_pool_cents")
    program = new_entity(store)
    program.update({
        "name": name,
        "fiscal_year": fiscal_year,
        "total_budget_cents": total_budget,
        "contingency_pool_cents": pool,
        "committed_cents": 0,
        "actuals_cents": 0,
        "contingency_reserved_cents": 0,
        "contingency_free_cents": pool,
        "budget_posture": "WITHIN_PLAN",
        "status": "SETUP",
    })
    store.programs[program["id"]] = program
    return ok(serialize(program), status=201)


@bp.route("/rollout/programs", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def list_programs():
    return list_response(store.programs, [("status", "status", "str")])


@bp.route("/rollout/programs/<programId>", methods=["GET"], strict_slashes=False)
@authed(ALL_ROLES)
def get_program(programId):
    return ok(serialize(get_or_404(store.programs, programId, "program")))


@bp.route("/rollout/programs/<programId>/activate", methods=["POST"], strict_slashes=False)
@authed(["ProgramDirector"])
def activate_program(programId):
    program = get_or_404(store.programs, programId, "program")
    require_state(program, ("SETUP",), TERMINAL)
    program["status"] = "ACTIVE"
    bump(program)
    return ok(serialize(program))


@bp.route("/rollout/programs/<programId>/complete", methods=["POST"], strict_slashes=False)
@authed(["ProgramDirector"])
def complete_program(programId):
    program = get_or_404(store.programs, programId, "program")
    require_state(program, ("ACTIVE",), TERMINAL)
    for site in store.sites.values():
        if site["program_id"] == program["id"] and site["status"] not in ("OPEN", "REMOVED"):
            raise ApiError("ERR_ACTIVE_SITES_REMAIN", 409,
                           "sites remain that are neither OPEN nor REMOVED")
    program["status"] = "COMPLETE"
    bump(program)
    return ok(serialize(program))
