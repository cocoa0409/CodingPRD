"""Teacher registration, reads and clearance maintenance (PRD §3.1)."""

from flask import Blueprint

import db
import middleware
from errors import ApiError
from middleware import endpoint
from routes import CLEARANCE_STATUSES, CREDENTIAL_AREAS, GRADE_BANDS, listing

bp = Blueprint("teachers", __name__)

CREATE_BODY = {
    "full_name": {"type": "string", "required": True},
    "employee_number": {"type": "string", "required": True},
    "credential_areas": {
        "type": "array",
        "required": True,
        "non_empty": True,
        "items_enum": CREDENTIAL_AREAS,
    },
    "grade_bands": {
        "type": "array",
        "required": True,
        "non_empty": True,
        "items_enum": GRADE_BANDS,
    },
    "max_weekly_caseload_minutes": {"type": "integer", "required": True, "min": 1},
    "safety_clearance_status": {"type": "string", "enum": CLEARANCE_STATUSES},
    "clearance_expires_on": {"type": "date", "required": True},
    "home_visit_eligible": {"type": "boolean"},
}

CLEARANCE_BODY = {
    "safety_clearance_status": {
        "type": "string",
        "required": True,
        "enum": CLEARANCE_STATUSES,
    },
    "clearance_expires_on": {"type": "date", "required": True},
    "home_visit_eligible": {"type": "boolean"},
}

LIST_QUERY = {
    "safety_clearance_status": {"type": "string", "enum": CLEARANCE_STATUSES},
    "home_visit_eligible": {"type": "boolean"},
}


@bp.post("/hhi/teachers")
@endpoint(["ProgramAdministrator"], body=CREATE_BODY, status=201)
def create_teacher():
    body = middleware.body()
    row = db.insert(
        "teachers",
        {
            "full_name": body["full_name"],
            "employee_number": body["employee_number"],
            "credential_areas": body["credential_areas"],
            "grade_bands": body["grade_bands"],
            "max_weekly_caseload_minutes": body["max_weekly_caseload_minutes"],
            "safety_clearance_status": body.get("safety_clearance_status", "CLEARED"),
            "clearance_expires_on": body["clearance_expires_on"],
            "home_visit_eligible": body.get("home_visit_eligible", True),
            "committed_weekly_minutes": 0,
            "over_cap": False,
        },
    )
    return middleware.obj(row)


@bp.get("/hhi/teachers/<teacher_id>")
@endpoint(["ProgramAdministrator", "CaseManager", "HomeboundTeacher", "ClassroomTeacher"])
def read_teacher(teacher_id):
    row = db.get("teachers", teacher_id)
    if row is None:
        raise ApiError("ERR_TEACHER_NOT_FOUND")
    return middleware.obj(row)


@bp.get("/hhi/teachers")
@endpoint(["ProgramAdministrator", "CaseManager"], query=LIST_QUERY)
def list_teachers():
    return listing("teachers", LIST_QUERY)


@bp.patch("/hhi/teachers/<teacher_id>/clearance")
@endpoint(["ProgramAdministrator"], body=CLEARANCE_BODY)
def update_clearance(teacher_id):
    row = db.get("teachers", teacher_id)
    if row is None:
        raise ApiError("ERR_TEACHER_NOT_FOUND")
    body = middleware.body()
    db.set_field(row, "safety_clearance_status", body["safety_clearance_status"])
    db.set_field(row, "clearance_expires_on", body["clearance_expires_on"])
    if "home_visit_eligible" in body:
        db.set_field(row, "home_visit_eligible", body["home_visit_eligible"])
    db.touch(row)  # the clearance revision increments version even when unchanged
    return middleware.obj(row)
