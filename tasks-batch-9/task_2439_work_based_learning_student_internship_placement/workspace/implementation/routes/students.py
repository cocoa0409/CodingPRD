"""Students and work permits (PRD 3.4)."""

from flask import Blueprint

import calc
import derive
from db import by_created, db, new_record, today_str, touch
from auth import require
from errors import fail
from response import created, listing, ok
from validation import f_bool, f_date, f_enum, f_int, f_num, f_str, get_body, pagination, paginate

bp = Blueprint("students", __name__)

PERMIT_CLASSES = ("MINOR_14_15", "MINOR_16_17", "ADULT_18_PLUS")
PERMIT_STATUSES = ("REQUESTED", "ISSUED", "EXPIRED", "REVOKED")


# --------------------------------------------------------------------------
# students
# --------------------------------------------------------------------------

@bp.post("/students")
def create_student():
    require("WblCoordinator")
    body = get_body()
    full_name = f_str(body, "full_name")
    birth_date = f_date(body, "birth_date")
    grade_level = f_int(body, "grade_level", minimum=9, maximum=12)
    gpa = f_num(body, "gpa", minimum=0, maximum=4)
    attendance_rate = f_num(body, "attendance_rate", minimum=0, maximum=1)
    certificate = f_bool(body, "student_learner_certificate", required=False, default=False)
    guardian_consent = f_bool(body, "guardian_consent_on_file", required=False, default=False)

    student = new_record()
    student.update({
        "full_name": full_name,
        "birth_date": birth_date,
        "grade_level": grade_level,
        "gpa": gpa,
        "attendance_rate": attendance_rate,
        "student_learner_certificate": certificate,
        "guardian_consent_on_file": guardian_consent,
        "eligibility_status": calc.student_eligibility_status(grade_level, gpa, attendance_rate),
        "ytd_wbl_hours": calc.rh(0, 2),
        "credits_earned_wbl": calc.rh(0, 2),
        "active_placement_count": 0,
    })
    db.students[student["id"]] = student
    return created(student)


@bp.patch("/students/<studentId>/academics")
def update_student_academics(studentId):
    require("WblCoordinator")
    student = derive.get_student(studentId)
    body = get_body()
    grade_level = f_int(body, "grade_level", minimum=9, maximum=12)
    gpa = f_num(body, "gpa", minimum=0, maximum=4)
    attendance_rate = f_num(body, "attendance_rate", minimum=0, maximum=1)

    student["grade_level"] = grade_level
    student["gpa"] = gpa
    student["attendance_rate"] = attendance_rate
    student["eligibility_status"] = calc.student_eligibility_status(
        grade_level, gpa, attendance_rate)
    touch(student)
    return ok(student)


@bp.get("/students/<studentId>")
def read_student(studentId):
    require("WblCoordinator", "ComplianceOfficer", "Student")
    return ok(derive.get_student(studentId))


# --------------------------------------------------------------------------
# work permits
# --------------------------------------------------------------------------

@bp.post("/work-permits")
def request_permit():
    require("WblCoordinator", "ComplianceOfficer")
    body = get_body()
    student = derive.get_student(f_str(body, "student_id"))
    permit_class = f_enum(body, "permit_class", PERMIT_CLASSES)
    hazardous = f_bool(body, "hazardous_endorsement", required=False, default=False)

    permit = new_record()
    permit.update({
        "student_id": student["id"],
        "permit_class": permit_class,
        "hazardous_endorsement": hazardous,
        "status": "REQUESTED",
        "issued_on": None,
        "expires_on": None,
        "issued_by_user_id": None,
        "revoked_reason": None,
    })
    db.work_permits[permit["id"]] = permit
    return created(permit)


@bp.post("/work-permits/<permitId>/issue")
def issue_permit(permitId):
    user_id, _role = require("ComplianceOfficer")
    permit = derive.get_permit(permitId)
    body = get_body()
    expires_on = f_date(body, "expires_on")

    if permit["status"] != "REQUESTED":
        fail("ERR_PERMIT_INVALID_STATE", "Only a requested work permit may be issued.")
    student = derive.get_student(permit["student_id"])
    if student["guardian_consent_on_file"] is not True:
        fail("ERR_GUARDIAN_CONSENT_MISSING",
             "The student's guardian consent is not on file.")
    issued_on = today_str()
    if expires_on < issued_on:
        fail("ERR_INVALID_REQUEST",
             "Field 'expires_on' must be on or after the issuance date.")

    permit["status"] = "ISSUED"
    permit["issued_on"] = issued_on
    permit["expires_on"] = expires_on
    permit["issued_by_user_id"] = user_id
    touch(permit)
    return ok(permit)


@bp.post("/work-permits/<permitId>/revoke")
def revoke_permit(permitId):
    require("ComplianceOfficer")
    permit = derive.get_permit(permitId)
    body = get_body()
    reason = f_str(body, "revoked_reason")

    if permit["status"] != "ISSUED":
        fail("ERR_PERMIT_INVALID_STATE", "Only an issued work permit may be revoked.")

    permit["status"] = "REVOKED"
    permit["revoked_reason"] = reason
    touch(permit)

    derive.flag_placements_of_student(permit["student_id"])
    return ok(permit)


@bp.get("/students/<id>/work-permits")
def list_student_permits(id):
    require("WblCoordinator", "ComplianceOfficer", "Student")
    student = derive.get_student(id)
    limit, offset = pagination()
    rows = by_created([p for p in db.work_permits.values()
                       if p["student_id"] == student["id"]])
    page, total = paginate(rows, limit, offset)
    return listing(page, total, limit, offset)
