"""Course endpoints (PRD 3.1). State machine: ACTIVE -> RETIRED."""
from flask import Blueprint

from errors import raise_error, ERR_INVALID_STATE
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response
from services.core import new_record, public, touch
from validate import get_body, req_int, req_number, req_str, require_path_resource

bp = Blueprint("courses", __name__)


@bp.post("/courses")
def create_course():
    authorized(["DualCreditAdmin"])
    body = get_body()
    rec = new_record(
        "courses",
        {
            "course_code": req_str(body, "course_code"),
            "title": req_str(body, "title"),
            "college_credit_hours": req_int(body, "college_credit_hours", minimum=1),
            "hs_credit_units": req_number(body, "hs_credit_units", gt=0),
            "placement_exam_code": req_str(body, "placement_exam_code"),
            "min_placement_score": req_int(body, "min_placement_score", minimum=0),
            "status": "ACTIVE",
        },
    )
    return success_object(public(rec), status=201)


@bp.get("/courses")
def list_courses():
    return list_response("courses")


@bp.get("/courses/<rid>")
def get_course(rid):
    return get_one("courses", rid)


@bp.post("/courses/<rid>/retire")
def retire_course(rid):
    authorized(["DualCreditAdmin"])
    rec = require_path_resource("courses", rid)
    if rec["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "only an ACTIVE course can be retired")
    rec["status"] = "RETIRED"
    touch(rec)
    return success_object(public(rec))
