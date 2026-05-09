"""HousingProgram + clock-advance routes."""
from flask import Blueprint

from common import (
    check_version,
    get_json_body,
    get_program_or_404,
    paginate,
    require_field,
    require_int,
    stamp_new,
    stamp_update,
)
from db import db
from errors import api_error
from middleware import require_roles
from response import success
from services.allocation import run_clock_sweeps

bp = Blueprint("programs", __name__)


# ----------------------------------------------------------------------------
# POST /housing-programs   — HousingDirector
# ----------------------------------------------------------------------------
@bp.post("/housing-programs")
def create_program():
    require_roles("HousingDirector")
    body = get_json_body()

    name = require_field(body, "name")
    if not isinstance(name, str) or not name.strip():
        raise api_error("ERR_INVALID_REQUEST", "name must be a non-empty string")

    description = body.get("description")
    if description is not None and not isinstance(description, str):
        raise api_error("ERR_INVALID_REQUEST", "description must be a string")

    notice_period = body.get("notice_period_length", 7)
    grace_period = body.get("grace_period_length", 6)
    try:
        notice_period = int(notice_period)
        grace_period = int(grace_period)
    except (TypeError, ValueError):
        raise api_error("ERR_INVALID_REQUEST",
                        "notice_period_length and grace_period_length must be integers")
    if notice_period < 1:
        raise api_error("ERR_INVALID_REQUEST", "notice_period_length must be >= 1")
    if grace_period < 1:
        raise api_error("ERR_INVALID_REQUEST", "grace_period_length must be >= 1")

    income_t = require_int(body, "per_capita_income_threshold_cents", minimum=0)
    asset_t = require_int(body, "per_capita_asset_threshold_cents", minimum=0)

    program = {
        "name": name,
        "description": description,
        "current_period_index": 0,
        "notice_period_length": notice_period,
        "grace_period_length": grace_period,
        "per_capita_income_threshold_cents": income_t,
        "per_capita_asset_threshold_cents": asset_t,
    }
    stamp_new(program)
    db.programs[program["id"]] = program
    return success(program, status=201)


# ----------------------------------------------------------------------------
# GET /housing-programs
# ----------------------------------------------------------------------------
@bp.get("/housing-programs")
def list_programs():
    require_roles("HousingDirector", "HousingOfficer", "Applicant", "Citizen",
                  "IntegrationGateway")
    items = list(db.programs.values())
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


# ----------------------------------------------------------------------------
# GET /housing-programs/{programId}
# ----------------------------------------------------------------------------
@bp.get("/housing-programs/<program_id>")
def get_program(program_id):
    require_roles("HousingDirector", "HousingOfficer", "Applicant", "Citizen",
                  "IntegrationGateway")
    program = get_program_or_404(program_id)
    return success(program)


# ----------------------------------------------------------------------------
# POST /housing-programs/{programId}/clock/advance — HousingDirector
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/clock/advance")
def advance_clock(program_id):
    user_id, _ = require_roles("HousingDirector")
    program = get_program_or_404(program_id)
    body = get_json_body()
    check_version(program, body)
    by_periods = require_int(body, "by_periods", minimum=1, maximum=10000)

    with db.lock:
        program["current_period_index"] = int(program["current_period_index"]) + by_periods
        stamp_update(program)
        run_clock_sweeps(program, actor_user_id=user_id)
    return success(program)
