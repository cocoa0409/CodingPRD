"""Teacher staffing and the weekly minute allocation (PRD §3.4)."""

from flask import Blueprint

import clock
import db
import middleware
from errors import ApiError
from middleware import endpoint
from routes import ASSIGNMENT_ROLES, ASSIGNMENT_STATUSES, RELEASE_REASONS, listing
from services import logic

bp = Blueprint("assignments", __name__)

READ_ROLES = ["ProgramAdministrator", "CaseManager", "HomeboundTeacher"]

CREATE_BODY = {
    "case_id": {"type": "string", "required": True},
    "role": {"type": "string", "required": True, "enum": ASSIGNMENT_ROLES},
    "teacher_id": {"type": "string"},
}

LIST_QUERY = {
    "case_id": {"type": "string"},
    "teacher_id": {"type": "string"},
    "role": {"type": "string", "enum": ASSIGNMENT_ROLES},
    "status": {"type": "string", "enum": ASSIGNMENT_STATUSES},
}


def load_assignment(assignment_id):
    row = db.get("assignments", assignment_id)
    if row is None:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND")
    return row


@bp.post("/hhi/assignments")
@endpoint(["CaseManager"], body=CREATE_BODY, status=201)
def create_assignment():
    body = middleware.body()

    teacher = None
    if "teacher_id" in body:                                    # tier 5: teacher first
        teacher = db.get("teachers", body["teacher_id"])
        if teacher is None:
            raise ApiError("ERR_TEACHER_NOT_FOUND")
    case = db.get("cases", body["case_id"])
    if case is None:
        raise ApiError("ERR_CASE_NOT_FOUND")

    role = body["role"]
    if role == "PRIMARY":                                        # tier 11
        for other in db.by_case("assignments", case["id"]):
            if other["role"] == "PRIMARY" and other["status"] in ("PROPOSED", "ACTIVE"):
                raise ApiError("ERR_DUPLICATE_PRIMARY_ASSIGNMENT")

    student = logic.student_of(case)
    if teacher is not None:                                      # tier 12
        if student["grade_band"] not in teacher["grade_bands"]:
            raise ApiError("ERR_TEACHER_BAND_MISMATCH")
    else:                                                        # tier 14
        teacher = logic.select_teacher(case, role)

    row = db.insert(
        "assignments",
        {
            "case_id": case["id"],
            "teacher_id": teacher["id"],
            "role": role,
            "status": "PROPOSED",
            "weekly_committed_minutes": 0,
            "accepted_at": None,
            "released_at": None,
            "release_reason": None,
            "decline_reason": None,
        },
    )
    return middleware.obj(row)


@bp.get("/hhi/assignments/<assignment_id>")
@endpoint(READ_ROLES)
def read_assignment(assignment_id):
    return middleware.obj(load_assignment(assignment_id))


@bp.get("/hhi/assignments")
@endpoint(READ_ROLES, query=LIST_QUERY)
def list_assignments():
    return listing("assignments", LIST_QUERY)


@bp.post("/hhi/assignments/<assignment_id>/accept")
@endpoint(["HomeboundTeacher"])
def accept_assignment(assignment_id):
    assignment = load_assignment(assignment_id)
    if assignment["teacher_id"] != middleware.user_id():         # tier 6
        raise ApiError("ERR_NOT_ASSIGNED_TEACHER")
    if assignment["status"] != "PROPOSED":                       # tier 8
        raise ApiError("ERR_ASSIGNMENT_NOT_PROPOSED")

    teacher = logic.teacher_of(assignment)
    if teacher["safety_clearance_status"] == "EXPIRED":          # tier 10
        raise ApiError("ERR_TEACHER_CLEARANCE_EXPIRED")

    case = db.get("cases", assignment["case_id"])
    prospective = logic.prospective_allocation(case, assignment["role"])
    if (                                                          # tier 14
        teacher["committed_weekly_minutes"] + prospective
        > teacher["max_weekly_caseload_minutes"]
    ):
        raise ApiError("ERR_TEACHER_CASELOAD_EXCEEDED")

    db.set_field(assignment, "status", "ACTIVE")
    db.set_field(assignment, "accepted_at", clock.instant_str())
    logic.recompute_allocation(case)
    return middleware.obj(assignment)


@bp.post("/hhi/assignments/<assignment_id>/decline")
@endpoint(["HomeboundTeacher"], body={"decline_reason": {"type": "string", "required": True}})
def decline_assignment(assignment_id):
    assignment = load_assignment(assignment_id)
    if assignment["teacher_id"] != middleware.user_id():         # tier 6
        raise ApiError("ERR_NOT_ASSIGNED_TEACHER")
    if assignment["status"] != "PROPOSED":                       # tier 8
        raise ApiError("ERR_ASSIGNMENT_NOT_PROPOSED")

    db.set_field(assignment, "status", "DECLINED")
    db.set_field(assignment, "decline_reason", middleware.body()["decline_reason"])
    db.set_field(assignment, "weekly_committed_minutes", 0)
    return middleware.obj(assignment)


@bp.post("/hhi/assignments/<assignment_id>/release")
@endpoint(
    ["ProgramAdministrator"],
    body={"release_reason": {"type": "string", "required": True, "enum": RELEASE_REASONS}},
)
def release_assignment(assignment_id):
    assignment = load_assignment(assignment_id)
    if assignment["status"] != "ACTIVE":                          # tier 8
        raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE")
    for session in db.rows("sessions"):
        if session["assignment_id"] == assignment["id"] and session["status"] == "SCHEDULED":
            raise ApiError("ERR_ASSIGNMENT_HAS_SCHEDULED_SESSIONS")

    db.set_field(assignment, "status", "RELEASED")
    db.set_field(assignment, "release_reason", middleware.body()["release_reason"])
    db.set_field(assignment, "released_at", clock.instant_str())
    db.set_field(assignment, "weekly_committed_minutes", 0)
    logic.recompute_allocation(db.get("cases", assignment["case_id"]))
    return middleware.obj(assignment)
