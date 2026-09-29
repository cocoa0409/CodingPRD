"""Student registration, reads and enrollment posture (PRD §3.1)."""

from flask import Blueprint

import db
import middleware
from errors import ApiError
from middleware import endpoint
from routes import ENROLLMENT_STATUSES, GRADE_BANDS, SPECIAL_ED_STATUSES, listing
from validation import fail

bp = Blueprint("students", __name__)

READ_ROLES = ["ProgramAdministrator", "CaseManager", "NurseReviewer"]

CREATE_BODY = {
    "student_number": {"type": "string", "required": True, "min_len": 1, "max_len": 32},
    "full_name": {"type": "string", "required": True},
    "grade_level": {"type": "integer", "required": True, "min": 0, "max": 12},
    "campus_code": {"type": "string", "required": True},
    "special_ed_status": {"type": "string", "enum": SPECIAL_ED_STATUSES},
    "iep_service_minutes_weekly": {"type": "integer", "min": 0},
    "enrollment_status": {"type": "string", "enum": ENROLLMENT_STATUSES},
}

LIST_QUERY = {
    "student_number": {"type": "string"},
    "campus_code": {"type": "string"},
    "enrollment_status": {"type": "string", "enum": ENROLLMENT_STATUSES},
    "grade_band": {"type": "string", "enum": GRADE_BANDS},
}


def grade_band(grade_level):
    if grade_level <= 5:
        return "PRIMARY"
    if grade_level <= 8:
        return "MIDDLE"
    return "HIGH"


@bp.post("/hhi/students")
@endpoint(["ProgramAdministrator"], body=CREATE_BODY, status=201)
def create_student():
    body = middleware.body()
    special_ed_status = body.get("special_ed_status", "NONE")
    iep_minutes = body.get("iep_service_minutes_weekly", 0)

    if special_ed_status == "NONE" and iep_minutes != 0:
        fail("iep_service_minutes_weekly must be 0 when special_ed_status is NONE.")
    if special_ed_status == "IEP" and iep_minutes <= 0:
        fail("iep_service_minutes_weekly must be greater than 0 when special_ed_status is IEP.")

    number = body["student_number"]
    if any(s["student_number"] == number for s in db.store["students"].values()):
        raise ApiError("ERR_DUPLICATE_STUDENT_NUMBER")

    row = db.insert(
        "students",
        {
            "student_number": number,
            "full_name": body["full_name"],
            "grade_level": body["grade_level"],
            "campus_code": body["campus_code"],
            "special_ed_status": special_ed_status,
            "iep_service_minutes_weekly": iep_minutes,
            "enrollment_status": body.get("enrollment_status", "ENROLLED"),
            "grade_band": grade_band(body["grade_level"]),
        },
    )
    return middleware.obj(row)


@bp.get("/hhi/students/<student_id>")
@endpoint(READ_ROLES)
def read_student(student_id):
    row = db.get("students", student_id)
    if row is None:
        raise ApiError("ERR_STUDENT_NOT_FOUND")
    return middleware.obj(row)


@bp.get("/hhi/students")
@endpoint(READ_ROLES, query=LIST_QUERY)
def list_students():
    return listing("students", LIST_QUERY)


@bp.post("/hhi/students/<student_id>/enrollment")
@endpoint(
    ["ProgramAdministrator"],
    body={
        "enrollment_status": {
            "type": "string",
            "required": True,
            "enum": ENROLLMENT_STATUSES,
        }
    },
)
def set_enrollment(student_id):
    row = db.get("students", student_id)
    if row is None:
        raise ApiError("ERR_STUDENT_NOT_FOUND")
    db.set_field(row, "enrollment_status", middleware.body()["enrollment_status"])
    db.touch(row)  # the enrollment change increments version even when unchanged
    return middleware.obj(row)
