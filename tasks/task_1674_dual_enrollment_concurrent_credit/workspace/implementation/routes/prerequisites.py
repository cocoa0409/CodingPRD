"""Prerequisite edge endpoints (PRD 3.2). DAG rules live in
services.calculations.check_new_prerequisite_edge (calculation 8)."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from routes.helpers import arg, get_one, list_response
from services.calculations import check_new_prerequisite_edge
from services.core import new_record, public
from validate import get_body, opt_enum, req_str, require_body_ref

bp = Blueprint("prerequisites", __name__)

MIN_GRADES = {"A", "B", "C"}


@bp.post("/prerequisites")
def create_prerequisite():
    authorized(["DualCreditAdmin"])
    body = get_body()
    course_id = req_str(body, "course_id")
    requires_course_id = req_str(body, "requires_course_id")
    min_grade = opt_enum(body, "min_grade", MIN_GRADES, default="C")
    # Priority 5: body FKs in declared input order.
    require_body_ref("courses", course_id, "course_id")
    require_body_ref("courses", requires_course_id, "requires_course_id")
    # Priority 15: self-edge -> duplicate -> cycle.
    check_new_prerequisite_edge(course_id, requires_course_id)
    rec = new_record(
        "prerequisites",
        {
            "course_id": course_id,
            "requires_course_id": requires_course_id,
            "min_grade": min_grade,
        },
    )
    return success_object(public(rec), status=201)


@bp.get("/prerequisites")
def list_prerequisites():
    return list_response(
        "prerequisites",
        {"course_id": arg("course_id"), "requires_course_id": arg("requires_course_id")},
    )


@bp.get("/prerequisites/<rid>")
def get_prerequisite(rid):
    return get_one("prerequisites", rid)
