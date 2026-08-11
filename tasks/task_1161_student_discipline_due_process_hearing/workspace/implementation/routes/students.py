"""Students (PRD §3.1)."""
from flask import Blueprint, request

from db import db, stamp, serialize
from errors import raise_err, ERR_INVALID_REQUEST
from middleware import endpoint
from response import success
from routes.common import get_or_404, guardian_owns, render_list
from services.calc import DEMOGRAPHIC_GROUPS
from util import is_int, parse_dt

bp = Blueprint("students", __name__)

DISABILITY_STATUSES = {"NONE", "IEP", "SECTION_504"}
ENROLLMENT_STATUSES = {"ENROLLED", "ALT_ED_PENDING", "IN_ALT_ED"}


@bp.post("/students")
@endpoint("DistrictAdmin", "SchoolAdministrator")
def create_student(ctx):
    b = ctx.body
    full_name = b.get("full_name")
    dob = parse_dt(b.get("date_of_birth"))
    grade = b.get("grade_level")
    group = b.get("demographic_group")
    guardian_id = b.get("guardian_id")
    disability = b.get("disability_status", "NONE")

    if not isinstance(full_name, str) or not full_name:
        raise_err(ERR_INVALID_REQUEST, "full_name is required")
    if dob is None:
        raise_err(ERR_INVALID_REQUEST, "date_of_birth must be a valid ISO 8601 date")
    if not is_int(grade) or grade < 6 or grade > 12:
        raise_err(ERR_INVALID_REQUEST, "grade_level must be an integer in [6, 12]")
    if group not in DEMOGRAPHIC_GROUPS:
        raise_err(ERR_INVALID_REQUEST, "demographic_group is not a declared value")
    if not isinstance(guardian_id, str) or not guardian_id:
        raise_err(ERR_INVALID_REQUEST, "guardian_id is required")
    if disability not in DISABILITY_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "disability_status is not a declared value")

    student = stamp(
        {
            "full_name": full_name,
            "date_of_birth": dob,
            "grade_level": grade,
            "demographic_group": group,
            "disability_status": disability,
            "guardian_id": guardian_id,
            "enrollment_status": "ENROLLED",
            "cumulative_suspension_days": 0,
            "last_case_closed_at": None,
        }
    )
    db.students[student["id"]] = student
    return success(serialize(student), 201)


@bp.get("/students/<sid>")
@endpoint(
    "DistrictAdmin",
    "SchoolAdministrator",
    "StudentServicesDirector",
    "HearingOfficer",
    "ParentGuardian",
)
def get_student(ctx, sid):
    student = get_or_404(db.students, sid, "student")
    guardian_owns(ctx, student)
    return success(serialize(student))


@bp.get("/students")
@endpoint("DistrictAdmin", "SchoolAdministrator", "StudentServicesDirector")
def list_students(ctx):
    group = request.args.get("demographic_group")
    disability = request.args.get("disability_status")
    enrollment = request.args.get("enrollment_status")
    if group is not None and group not in DEMOGRAPHIC_GROUPS:
        raise_err(ERR_INVALID_REQUEST, "demographic_group filter is not a declared value")
    if disability is not None and disability not in DISABILITY_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "disability_status filter is not a declared value")
    if enrollment is not None and enrollment not in ENROLLMENT_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "enrollment_status filter is not a declared value")
    return render_list(
        db.students,
        {
            "demographic_group": group,
            "disability_status": disability,
            "enrollment_status": enrollment,
        },
    )
