"""Student endpoints (PRD 3.5). State machine: ELIGIBLE -> SUSPENDED."""
from flask import Blueprint

from errors import raise_error, ERR_INVALID_STATE
from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.core import new_record, public, touch
from validate import get_body, req_int, req_str, require_body_ref, require_path_resource

bp = Blueprint("students", __name__)


@bp.post("/students")
def create_student():
    authorized(["HsCoordinator"])
    body = get_body()
    full_name = req_str(body, "full_name")
    high_school_id = req_str(body, "high_school_id")
    grade_level = req_int(body, "grade_level", minimum=9, maximum=12)
    require_body_ref("high_schools", high_school_id, "high_school_id")
    rec = new_record(
        "students",
        {
            "full_name": full_name,
            "high_school_id": high_school_id,
            "grade_level": grade_level,
            "status": "ELIGIBLE",
            "college_gpa": 0.0,
            "hs_gpa": 0.0,
        },
    )
    return success_object(public(rec), status=201)


@bp.get("/students")
def list_students():
    return list_response("students", {"high_school_id": arg("high_school_id")})


@bp.get("/students/<rid>")
def get_student(rid):
    return get_one("students", rid)


@bp.post("/students/<rid>/suspend")
def suspend_student(rid):
    authorized(["DualCreditAdmin"])
    rec = require_path_resource("students", rid)
    if rec["status"] != "ELIGIBLE":
        raise_error(ERR_INVALID_STATE, "only an ELIGIBLE student can be suspended")
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success_object(public(rec))
