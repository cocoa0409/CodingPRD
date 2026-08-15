"""IncentiveProgram and ProjectIncentive endpoints (PRD 3.7)."""
from flask import Blueprint, request

from db import DB
from errors import ApiError
from middleware import auth_headers, require_role
from response import ok, ok_list
from services import (
    LEVEL_RANK,
    get_program,
    get_project,
    get_project_incentive,
    ser_program,
    ser_project_incentive,
    sorted_created,
    stamp,
    touch,
)
from util import (
    INCENTIVE_TYPES,
    LEVELS,
    as_bool,
    as_enum,
    as_int,
    as_str,
    body,
    pagination_args,
    required,
)

bp = Blueprint("incentives", __name__)


# --- IncentiveProgram ---

@bp.post("/incentive-programs")
def create_program():
    _user_id, role = auth_headers()
    data = body()
    program_name = as_str(required(data, "program_name"), "program_name")
    incentive_type = as_enum(
        required(data, "incentive_type"), INCENTIVE_TYPES, "incentive_type"
    )
    benefit = as_int(required(data, "benefit_amount_cents"), "benefit_amount_cents")
    if benefit <= 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "benefit_amount_cents must be > 0")
    minimum_level = as_enum(
        required(data, "minimum_certification_level"), LEVELS, "minimum_certification_level"
    )
    is_combinable = as_bool(required(data, "is_combinable"), "is_combinable")
    require_role(role, {"ProgramAdmin"})
    for p in DB["incentive_programs"].values():
        if p["program_name"] == program_name:
            raise ApiError("ERR_INVALID_REQUEST", 400, "program_name must be unique")
    rec = stamp(
        {
            "program_name": program_name,
            "incentive_type": incentive_type,
            "benefit_amount_cents": benefit,
            "minimum_certification_level": minimum_level,
            "is_combinable": is_combinable,
        }
    )
    DB["incentive_programs"][rec["id"]] = rec
    return ok(ser_program(rec), status=201)


@bp.get("/incentive-programs")
def list_programs():
    auth_headers()
    incentive_type = request.args.get("incentive_type")
    items = list(DB["incentive_programs"].values())
    if incentive_type is not None:
        items = [p for p in items if p["incentive_type"] == incentive_type]
    items = sorted_created(items)
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_program(p) for p in page], total, limit, offset)


@bp.get("/incentive-programs/<program_id>")
def get_one_program(program_id):
    auth_headers()
    return ok(ser_program(get_program(program_id)))


# --- ProjectIncentive ---

@bp.post("/project-incentives")
def create_project_incentive():
    _user_id, role = auth_headers()
    data = body()
    project_id = as_str(required(data, "project_id"), "project_id")
    program_id = as_str(required(data, "incentive_program_id"), "incentive_program_id")
    require_role(role, {"ProjectAdministrator"})
    project = get_project(project_id)
    program = get_program(program_id)
    for a in DB["project_incentives"].values():
        if (
            a["project_id"] == project["id"]
            and a["incentive_program_id"] == program["id"]
            and a["status"] in ("APPLIED", "APPROVED", "DISBURSED")
        ):
            raise ApiError(
                "ERR_DUPLICATE_INCENTIVE_APPLICATION",
                409,
                "A live application for this program already exists on the project",
            )
    rec = stamp(
        {
            "project_id": project["id"],
            "incentive_program_id": program["id"],
            "claimed_amount_cents": 0,
            "status": "APPLIED",
        }
    )
    DB["project_incentives"][rec["id"]] = rec
    return ok(ser_project_incentive(rec), status=201)


@bp.get("/project-incentives")
def list_project_incentives():
    auth_headers()
    items = list(DB["project_incentives"].values())
    project_id = request.args.get("project_id")
    program_id = request.args.get("incentive_program_id")
    status = request.args.get("status")
    if project_id is not None:
        items = [a for a in items if a["project_id"] == project_id]
    if program_id is not None:
        items = [a for a in items if a["incentive_program_id"] == program_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sorted_created(items)
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_project_incentive(a) for a in page], total, limit, offset)


@bp.get("/project-incentives/<project_incentive_id>")
def get_one_project_incentive(project_incentive_id):
    auth_headers()
    return ok(ser_project_incentive(get_project_incentive(project_incentive_id)))


@bp.post("/project-incentives/<project_incentive_id>/approve")
def approve_project_incentive(project_incentive_id):
    _user_id, role = auth_headers()
    body()
    require_role(role, {"ProgramAdmin"})
    app_rec = get_project_incentive(project_incentive_id)
    if app_rec["status"] != "APPLIED":
        raise ApiError("ERR_INVALID_INCENTIVE_STATE", 409, "approve requires APPLIED")
    project = DB["projects"][app_rec["project_id"]]
    program = DB["incentive_programs"][app_rec["incentive_program_id"]]
    # Fiscal gates (ladder stage 11): certification-gated money.
    if project["status"] != "CERTIFIED":
        raise ApiError(
            "ERR_PROJECT_NOT_CERTIFIED", 409, "Project is not CERTIFIED"
        )
    if LEVEL_RANK[project["certified_level"]] < LEVEL_RANK[program["minimum_certification_level"]]:
        raise ApiError(
            "ERR_CERTIFICATION_LEVEL_INSUFFICIENT",
            422,
            "Project certified level is below the program minimum",
        )
    app_rec["status"] = "APPROVED"
    app_rec["claimed_amount_cents"] = program["benefit_amount_cents"]
    touch(app_rec)
    return ok(ser_project_incentive(app_rec))


@bp.post("/project-incentives/<project_incentive_id>/disburse")
def disburse_project_incentive(project_incentive_id):
    _user_id, role = auth_headers()
    body()
    require_role(role, {"ProgramAdmin"})
    app_rec = get_project_incentive(project_incentive_id)
    if app_rec["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_INCENTIVE_STATE", 409, "disburse requires APPROVED")
    app_rec["status"] = "DISBURSED"
    touch(app_rec)
    return ok(ser_project_incentive(app_rec))
