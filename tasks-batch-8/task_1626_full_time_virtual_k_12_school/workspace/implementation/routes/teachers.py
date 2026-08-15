"""Teacher and TeacherAssignment endpoints (PRD section 3.6)."""

import db
import services
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_TEACHER_NOT_CERTIFIED_IN_STATE,
    ERR_CASELOAD_EXCEEDED,
)
from middleware import authenticate
from response import success_obj, success_list
from routes import make_blueprint
from util import (
    body_json, check_shape, pagination_params, paginate, apply_filters,
    require_fk, exist_body_fks,
)

bp = make_blueprint("teachers")

TEACHER_READ_ROLES = ["PlatformAdmin", "AcademicDirector", "SpecialEdCoordinator",
                      "EnrollmentOfficer"]
ASSIGNMENT_SUBJECTS = ["ELA", "MATH", "SCIENCE", "SOCIAL_STUDIES", "SPECIAL_ED"]


def _public_teacher(teacher):
    services.reconcile_teacher(teacher)
    return db.public(teacher)


# --- Teacher -----------------------------------------------------------------

@bp.post("/teachers")
def create_teacher():
    authenticate(["AcademicDirector", "PlatformAdmin"])
    body = body_json()
    check_shape(body, {
        "full_name": {"type": "string", "required": True},
        "certification_state_codes": {"type": "array", "required": True,
                                      "items": {"type": "string"}},
        "caseload_cap": {"type": "integer", "required": True, "min": 1},
    })
    teacher = db.new_entity("teachers", {
        "full_name": body["full_name"],
        "certification_state_codes": list(body["certification_state_codes"]),
        "caseload_cap": body["caseload_cap"],
        "current_caseload": 0,
        "teacher_status": "ACTIVE",
    })
    return success_obj(db.public(teacher), 201)


@bp.get("/teachers/<tid>")
def get_teacher(tid):
    authenticate(TEACHER_READ_ROLES)
    teacher = require_fk("teachers", tid, "teacher")
    return success_obj(_public_teacher(teacher), 200)


@bp.get("/teachers")
def list_teachers():
    authenticate(TEACHER_READ_ROLES)
    limit, offset = pagination_params()
    items = db.all_of("teachers")
    page, total, has_more = paginate(items, limit, offset)
    return success_list([_public_teacher(t) for t in page], limit, offset, total, has_more)


# --- TeacherAssignment --------------------------------------------------------

@bp.post("/teacher-assignments")
def create_teacher_assignment():
    authenticate(["AcademicDirector"])
    body = body_json()
    # Body FK existence (priority 4).
    exist_body_fks(body, {
        "teacher_id": ("teachers", "teacher"),
        "student_id": ("students", "student"),
    })
    # State admissibility (priority 5): student must be ENROLLED.
    student = db.get("students", body.get("student_id")) if body.get("student_id") else None
    teacher = db.get("teachers", body.get("teacher_id")) if body.get("teacher_id") else None
    if student is not None and student["enrollment_status"] != "ENROLLED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "teacher assignment requires an ENROLLED student")
    # Certification (priority 7) reports ahead of capacity (priority 9).
    if student is not None and teacher is not None:
        district = db.get("districts", student["district_of_residence_id"])
        state_code = district["state_code"] if district else None
        if state_code not in teacher["certification_state_codes"]:
            raise ApiError(ERR_TEACHER_NOT_CERTIFIED_IN_STATE, 422,
                           "teacher is not certified in the student's district state")
        # Caseload cap: filling the cap exactly is allowed; cap+1 is rejected.
        services.reconcile_teacher(teacher)
        if teacher["current_caseload"] + 1 > teacher["caseload_cap"]:
            raise ApiError(ERR_CASELOAD_EXCEEDED, 422,
                           "teacher caseload cap would be exceeded")
    # Input shape (priority 16).
    check_shape(body, {
        "teacher_id": {"type": "string", "required": True},
        "student_id": {"type": "string", "required": True},
        "subject": {"type": "enum", "required": True, "values": ASSIGNMENT_SUBJECTS},
    })
    assignment = db.new_entity("teacher_assignments", {
        "teacher_id": body["teacher_id"],
        "student_id": body["student_id"],
        "subject": body["subject"],
        "assignment_status": "ASSIGNED",
        "assigned_at": db.fmt_ts(db.now()),
        "ended_at": None,
    })
    teacher["current_caseload"] += 1
    db.touch(teacher)
    return success_obj(db.public(assignment), 201)


@bp.get("/teacher-assignments/<aid>")
def get_teacher_assignment(aid):
    authenticate(["PlatformAdmin", "AcademicDirector"])
    assignment = require_fk("teacher_assignments", aid, "teacher assignment")
    return success_obj(db.public(assignment), 200)


@bp.get("/teachers/<tid>/teacher-assignments")
def list_teacher_assignments(tid):
    authenticate(["PlatformAdmin", "AcademicDirector"])
    teacher = require_fk("teachers", tid, "teacher")
    limit, offset = pagination_params()
    items = [a for a in db.all_of("teacher_assignments")
             if a["teacher_id"] == teacher["id"]]
    items = apply_filters(items, ["assignment_status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(a) for a in page], limit, offset, total, has_more)


@bp.get("/students/<sid>/teacher-assignments")
def list_student_teacher_assignments(sid):
    authenticate(["PlatformAdmin", "AcademicDirector", "EnrollmentOfficer"])
    student = require_fk("students", sid, "student")
    limit, offset = pagination_params()
    items = [a for a in db.all_of("teacher_assignments")
             if a["student_id"] == student["id"]]
    items = apply_filters(items, ["assignment_status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(a) for a in page], limit, offset, total, has_more)


@bp.post("/teacher-assignments/<aid>/end")
def end_teacher_assignment(aid):
    authenticate(["AcademicDirector"])
    assignment = require_fk("teacher_assignments", aid, "teacher assignment")
    if assignment["assignment_status"] != "ASSIGNED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only an ASSIGNED teacher assignment can be ended")
    assignment["assignment_status"] = "ENDED"
    assignment["ended_at"] = db.fmt_ts(db.now())
    db.touch(assignment)
    teacher = db.get("teachers", assignment["teacher_id"])
    if teacher is not None:
        teacher["current_caseload"] = max(0, teacher["current_caseload"] - 1)
        db.touch(teacher)
    return success_obj(db.public(assignment), 200)
