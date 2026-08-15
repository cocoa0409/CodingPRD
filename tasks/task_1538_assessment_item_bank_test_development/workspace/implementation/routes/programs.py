"""AssessmentProgram endpoints: create, list, get, clock advance."""
from flask import Blueprint

from db import db, next_seq
from middleware import authorized, ALL_ROLES
from response import success_object
from routes.helpers import public, list_response, get_one
from util import new_id, now_ts, parse_dt, fmt_dt, advance_program_clock, CLOCK_DEFAULT
from validate import get_body, req_str, req_enum, req_int, require_path_resource

bp = Blueprint("programs", __name__)

SUBJECTS = ["MATH", "ELA", "SCIENCE", "SOCIAL_STUDIES"]


@bp.post("/api/assessment-programs")
def create_program():
    caller = authorized(["ProgramDirector"])
    body = get_body()
    program_code = req_str(body, "program_code")
    subject = req_enum(body, "subject", SUBJECTS)
    grade_level = req_int(body, "grade_level", minimum=3, maximum=12)
    admin_year = req_int(body, "admin_year")

    now = now_ts()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "program_code": program_code,
        "subject": subject,
        "grade_level": grade_level,
        "admin_year": admin_year,
        "current_period_utc": CLOCK_DEFAULT,
        "status": "ACTIVE",
        "_clock_dt": parse_dt(CLOCK_DEFAULT),
        "_seq": next_seq(),
    }
    db["assessment_programs"][rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.get("/api/assessment-programs")
def list_programs():
    authorized(ALL_ROLES)
    return list_response("assessment_programs")


@bp.get("/api/assessment-programs/<pid>")
def get_program(pid):
    authorized(ALL_ROLES)
    rec = require_path_resource("assessment_programs", pid)
    return get_one(rec)


@bp.post("/api/assessment-programs/<pid>/clock/advance")
def advance_clock(pid):
    caller = authorized(["ProgramDirector"])
    rec = require_path_resource("assessment_programs", pid)
    body = get_body()
    by_seconds = req_int(body, "by_seconds")
    if by_seconds < 0:
        from errors import raise_error, ERR_INVALID_REQUEST
        raise_error(ERR_INVALID_REQUEST, "by_seconds must be >= 0")
    advance_program_clock(rec, by_seconds)
    from services.common import touch
    touch(rec)
    return success_object(public(rec))
