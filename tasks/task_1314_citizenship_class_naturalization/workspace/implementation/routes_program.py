"""Program singleton and logical clock endpoints."""
from flask import Blueprint

from auth import authenticate, require_roles, ROLES
from db import db, Rec, PROGRAM_DEFAULTS, stamp_new, parse_dt
from errors import conflict, err_not_found
from services import ser_program, run_sweeps
from util import json_body, success_obj, v_str, v_int, v_datetime

bp = Blueprint("program", __name__)

_INT_FIELDS = [
    "n400_fee_cents", "biometric_fee_cents", "translation_stipend_cents",
    "poverty_base_cents", "poverty_per_additional_cents",
    "full_waiver_threshold_pct", "partial_waiver_threshold_pct",
    "attendance_complete_bp", "attendance_midterm_floor_bp",
    "readiness_certify_threshold", "rfe_deadline_days",
    "accreditation_valid_months", "general_training_hours",
    "legal_supervised_hours", "renewal_training_hours",
    "promotion_offer_hours", "mock_buffer_minutes", "mock_max_attempts",
]


@bp.post("/naturalization/programs")
def create_program():
    body = json_body()
    name = v_str(body, "name")
    overrides = {f: v_int(body, f, required=False, minv=0) for f in _INT_FIELDS}
    authenticate()
    require_roles("ProgramAdmin")
    if db.program is not None:
        raise conflict("ERR_PROGRAM_EXISTS", "A Program configuration already exists")
    prog = Rec(name=name)
    for f in _INT_FIELDS:
        setattr(prog, f, overrides[f] if overrides[f] is not None else PROGRAM_DEFAULTS[f])
    stamp_new(prog)
    db.program = prog
    return success_obj(ser_program(prog), 201)


@bp.get("/naturalization/programs/current")
def get_program():
    authenticate()
    require_roles(*ROLES)
    if db.program is None:
        raise err_not_found("No Program configuration exists")
    return success_obj(ser_program(db.program))


@bp.post("/naturalization/_clock/set_current_utc")
def set_clock():
    body = json_body()
    raw, dt = v_datetime(body, "to_iso8601")
    authenticate()
    require_roles("ProgramAdmin")
    db.clock_dt = dt
    db.clock_raw = raw
    run_sweeps(dt)
    return success_obj({"current_utc": raw})
