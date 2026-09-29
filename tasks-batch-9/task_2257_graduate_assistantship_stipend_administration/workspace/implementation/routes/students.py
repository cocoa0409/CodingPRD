"""Graduate students and academic standing."""
from decimal import Decimal

from flask import Blueprint

import calc
import serialize
import validate as v
from db import db, insert, force_update
from errors import ApiError
from middleware import authenticate, require_owner
from response import ok, created
from services import effects, queries

bp = Blueprint("students", __name__)

DEGREE_LEVELS = ("MASTERS", "DOCTORAL")
VISA_TYPES = ("F1", "J1", "NONE")
SAP_STATUSES = ("SATISFACTORY", "PROBATION", "UNSATISFACTORY")

READ_ROLES = ["GradSchoolAdmin", "DepartmentAdmin", "GrantAccountant",
              "FacultySupervisor", "StudentUser"]


@bp.post("/students")
def create_student():
    authenticate(["GradSchoolAdmin"])
    body = v.body_dict()
    student_number = v.field_str(body, "student_number")
    full_name = v.field_str(body, "full_name")
    degree_level = v.field_enum(body, "degree_level", DEGREE_LEVELS)
    is_international = v.field_bool(body, "is_international")
    cumulative_gpa = v.field_decimal(body, "cumulative_gpa", minimum=0, maximum=4)
    visa_type = v.field_enum(body, "visa_type", VISA_TYPES, required=False, default="NONE")
    enrolled_credit_hours = v.field_int(body, "enrolled_credit_hours", required=False,
                                       default=0, minimum=0, maximum=24)
    external_weekly_hours = v.field_decimal(body, "external_weekly_hours", required=False,
                                            default=Decimal("0"), minimum=0, maximum=40)

    for row in db.students.values():
        if row["student_number"] == student_number:
            raise ApiError("ERR_DUPLICATE_STUDENT_NUMBER",
                           "student_number %s is already used" % student_number)

    row = insert(db.students, {
        "student_number": student_number,
        "full_name": full_name,
        "degree_level": degree_level,
        "is_international": is_international,
        "visa_type": visa_type,
        "enrolled_credit_hours": enrolled_credit_hours,
        "cumulative_gpa": cumulative_gpa,
        "external_weekly_hours": external_weekly_hours,
        "sap_status": "SATISFACTORY",
        "effort_cap_pct": calc.DEFAULT_EFFORT_CAP_PCT,
        "cap_override_by_user_id": None,
        "cap_override_justification": None,
        "total_effort_pct": 0,
        "assigned_hours_per_week": Decimal("0"),
        "tuition_benefit_ytd_cents": 0,
        "taxable_tuition_benefit_ytd_cents": 0,
    })
    return created(serialize.student(row))


@bp.get("/students/<student_id>")
def read_student(student_id):
    actor_id, role = authenticate(READ_ROLES)
    require_owner(actor_id, role, student_id)
    student = queries.student_or_404(student_id)
    return ok(serialize.student(student))


@bp.patch("/students/<student_id>/academic-progress")
def patch_progress(student_id):
    authenticate(["FacultySupervisor", "GradSchoolAdmin"])
    student = queries.student_or_404(student_id)
    body = v.body_dict()
    sap_status = v.field_enum(body, "sap_status", SAP_STATUSES, required=False)
    cumulative_gpa = v.field_decimal(body, "cumulative_gpa", required=False,
                                     minimum=0, maximum=4)
    enrolled_credit_hours = v.field_int(body, "enrolled_credit_hours", required=False,
                                        minimum=0, maximum=24)
    external_weekly_hours = v.field_decimal(body, "external_weekly_hours", required=False,
                                            minimum=0, maximum=40)

    patch = {}
    if sap_status is not None:
        patch["sap_status"] = sap_status
    if cumulative_gpa is not None:
        patch["cumulative_gpa"] = cumulative_gpa
    if enrolled_credit_hours is not None:
        patch["enrolled_credit_hours"] = enrolled_credit_hours
    if external_weekly_hours is not None:
        patch["external_weekly_hours"] = external_weekly_hours
    force_update(student, **patch)

    if sap_status in ("PROBATION", "UNSATISFACTORY"):
        effects.revoke_certifications(student["id"])
    return ok(serialize.student(student))


@bp.post("/students/<student_id>/effort-cap-override")
def effort_cap_override(student_id):
    actor_id, _ = authenticate(["GradSchoolAdmin"])
    student = queries.student_or_404(student_id)
    body = v.body_dict()
    approved_max = v.field_int(body, "approved_max_effort_pct", minimum=1, maximum=100)
    justification = v.field_str(body, "justification")
    force_update(student,
                 effort_cap_pct=approved_max,
                 cap_override_by_user_id=actor_id,
                 cap_override_justification=justification)
    return ok(serialize.student(student))
