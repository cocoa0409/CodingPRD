"""Students, faculty assessors and the graduation audit."""
from flask import Blueprint, request

from db import claims_of_student, db, new_row, order_rows
from errors import ApiError
from middleware import (ROLE_ASSESSOR, ROLE_COORDINATOR, ROLE_REGISTRAR,
                        ROLE_REVIEWER, ROLE_STUDENT, authenticate,
                        enforce_student_scope, find_or_404)
from response import created, ok, ok_list, read_pagination
from serializers import assessor_out, student_out
from services.capacity import (effective_cap_student, program_ceiling,
                               remaining_posted_only, remaining_reserved_inclusive)
from util import (as_bool, as_enum, as_int, as_str, json_body, present, require, touch)

bp = Blueprint("people", __name__)

ENROLLMENT_STATUSES = ["APPLICANT", "MATRICULATED", "WITHDRAWN", "GRADUATED"]
ASSESSOR_STATUSES = ["ACTIVE", "ON_LEAVE", "INACTIVE"]
DEFAULT_MAX_CONCURRENT = 10


@bp.post("/students")
def create_student():
    authenticate([ROLE_COORDINATOR, ROLE_REGISTRAR])
    body = json_body()
    program_id = require(body, "program_id")
    program = db.programs.get(program_id)
    if program is None:
        raise ApiError("ERR_PROGRAM_NOT_FOUND")
    student_number = as_str(require(body, "student_number"), "student_number", 1, 32)
    full_name = as_str(require(body, "full_name"), "full_name", 1)
    enrollment_status = "MATRICULATED"
    if present(body, "enrollment_status"):
        enrollment_status = as_enum(body["enrollment_status"], "enrollment_status", ENROLLMENT_STATUSES)
    transfer = 0
    if present(body, "transfer_credits_accepted"):
        transfer = as_int(body["transfer_credits_accepted"], "transfer_credits_accepted", 0)
    institutional = 0
    if present(body, "institutional_credits_earned"):
        institutional = as_int(body["institutional_credits_earned"], "institutional_credits_earned", 0)
    for existing in db.students.values():
        if existing["student_number"] == student_number:
            raise ApiError("ERR_INVALID_REQUEST", "student_number is already registered")

    student = new_row("Student")
    student.update({
        "student_number": student_number,
        "full_name": full_name,
        "program_id": program_id,
        "enrollment_status": enrollment_status,
        "transfer_credits_accepted": transfer,
        "institutional_credits_earned": institutional,
        "pla_credits_reserved": 0,
        "pla_credits_awarded": 0,
        "pla_credits_posted": 0,
        "pla_upper_division_committed": 0,
        "fee_paid_net_cents": 0,
    })
    db.students[student["id"]] = student
    return created(student_out(student))


@bp.get("/students/<student_id>")
def read_student(student_id):
    authenticate([ROLE_COORDINATOR, ROLE_REGISTRAR, ROLE_ASSESSOR, ROLE_REVIEWER, ROLE_STUDENT])
    student = find_or_404("students", student_id, "ERR_STUDENT_NOT_FOUND")
    return ok(student_out(student))


@bp.get("/students")
def list_students():
    authenticate([ROLE_COORDINATOR, ROLE_REGISTRAR])
    limit, offset = read_pagination()
    rows = list(db.students.values())
    for key in ("program_id", "enrollment_status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    rows = order_rows(rows, [(lambda r: r["student_number"], False)])
    return ok_list(rows, student_out, limit, offset)


@bp.patch("/students/<student_id>")
def amend_student(student_id):
    authenticate([ROLE_REGISTRAR, ROLE_COORDINATOR])
    student = find_or_404("students", student_id, "ERR_STUDENT_NOT_FOUND")
    body = json_body()
    if present(body, "enrollment_status"):
        student["enrollment_status"] = as_enum(body["enrollment_status"], "enrollment_status", ENROLLMENT_STATUSES)
    if present(body, "transfer_credits_accepted"):
        student["transfer_credits_accepted"] = as_int(
            body["transfer_credits_accepted"], "transfer_credits_accepted", 0)
    if present(body, "institutional_credits_earned"):
        student["institutional_credits_earned"] = as_int(
            body["institutional_credits_earned"], "institutional_credits_earned", 0)
    touch(student)
    return ok(student_out(student))


@bp.get("/students/<student_id>/graduation-audit")
def graduation_audit(student_id):
    ctx = authenticate([ROLE_REGISTRAR, ROLE_COORDINATOR, ROLE_STUDENT])
    enforce_student_scope(ctx, student_id)
    student = find_or_404("students", student_id, "ERR_STUDENT_NOT_FOUND")
    program = db.programs.get(student["program_id"])
    cap = effective_cap_student(program, student) if program else 0
    upper_posted = 0
    for claim in claims_of_student(student_id):
        if claim["credit_status"] != "POSTED":
            continue
        course = db.courses.get(claim["course_id"])
        if course is not None and course["level"] == "UPPER":
            upper_posted += claim["credits_awarded"] or 0
    posted = student["pla_credits_posted"]
    total_applied = student["institutional_credits_earned"] + student["transfer_credits_accepted"] + posted
    residency_ok = (
        student["institutional_credits_earned"] >= program["residency_min_credits"]
        and student["transfer_credits_accepted"] + posted
        <= program["total_credits_required"] - program["residency_min_credits"]
    ) if program else False
    if not residency_ok:
        audit_status = "RESIDENCY_DEFICIENT"
    elif posted > cap:
        audit_status = "PLA_CAP_VIOLATION"
    elif total_applied < program["total_credits_required"]:
        audit_status = "DEFICIENT_CREDITS"
    else:
        audit_status = "ELIGIBLE"
    data = {
        "student_id": student_id,
        "program_id": student["program_id"],
        "effective_pla_cap_credits": cap,
        "pla_credits_posted": posted,
        "pla_credits_reserved": student["pla_credits_reserved"],
        "pla_credits_awarded": student["pla_credits_awarded"],
        "pla_cap_remaining_posted_only": remaining_posted_only(program, student) if program else 0,
        "pla_cap_remaining_reserved_inclusive": remaining_reserved_inclusive(program, student) if program else 0,
        "upper_division_pla_posted": upper_posted,
        "upper_division_remaining": (program["pla_upper_division_max_credits"]
                                     - student["pla_upper_division_committed"]) if program else 0,
        "institutional_credits_earned": student["institutional_credits_earned"],
        "transfer_credits_accepted": student["transfer_credits_accepted"],
        "total_credits_applied": total_applied,
        "residency_satisfied": residency_ok,
        "audit_status": audit_status,
    }
    return ok(data)


# ---------------------------------------------------------------- assessors
@bp.post("/faculty-assessors")
def create_assessor():
    authenticate([ROLE_COORDINATOR])
    body = json_body()
    employee_number = as_str(require(body, "employee_number"), "employee_number", 1, 32)
    full_name = as_str(require(body, "full_name"), "full_name", 1)
    department_code = as_str(require(body, "department_code"), "department_code", 2, 8, r"^[A-Z0-9]{2,8}$")
    credential_rank = as_int(require(body, "credential_rank"), "credential_rank", 1, 3)
    max_concurrent = DEFAULT_MAX_CONCURRENT
    if present(body, "max_concurrent_assignments"):
        max_concurrent = as_int(body["max_concurrent_assignments"], "max_concurrent_assignments", 1, 10)
    panel = False
    if present(body, "appeal_panel_member"):
        panel = as_bool(body["appeal_panel_member"], "appeal_panel_member")
    status = "ACTIVE"
    if present(body, "status"):
        status = as_enum(body["status"], "status", ASSESSOR_STATUSES)
    for existing in db.assessors.values():
        if existing["employee_number"] == employee_number:
            raise ApiError("ERR_INVALID_REQUEST", "employee_number is already registered")

    assessor = new_row("FacultyAssessor")
    assessor.update({
        "employee_number": employee_number,
        "full_name": full_name,
        "department_code": department_code,
        "credential_rank": credential_rank,
        "max_concurrent_assignments": max_concurrent,
        "appeal_panel_member": panel,
        "status": status,
        "active_assignment_count": 0,
    })
    db.assessors[assessor["id"]] = assessor
    return created(assessor_out(assessor))


@bp.get("/faculty-assessors/<assessor_id>")
def read_assessor(assessor_id):
    authenticate([ROLE_COORDINATOR, ROLE_REGISTRAR, ROLE_ASSESSOR, ROLE_REVIEWER])
    assessor = find_or_404("assessors", assessor_id, "ERR_ASSESSOR_NOT_FOUND")
    return ok(assessor_out(assessor))


@bp.get("/faculty-assessors")
def list_assessors():
    authenticate([ROLE_COORDINATOR, ROLE_REGISTRAR])
    limit, offset = read_pagination()
    rows = list(db.assessors.values())
    for key in ("department_code", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    panel = request.args.get("appeal_panel_member")
    if panel is not None and panel != "":
        if panel.lower() in ("true", "1"):
            rows = [r for r in rows if r["appeal_panel_member"]]
        elif panel.lower() in ("false", "0"):
            rows = [r for r in rows if not r["appeal_panel_member"]]
        else:
            raise ApiError("ERR_INVALID_REQUEST", "appeal_panel_member must be a boolean")
    rows = order_rows(rows, [(lambda r: r["employee_number"], False)])
    return ok_list(rows, assessor_out, limit, offset)


@bp.patch("/faculty-assessors/<assessor_id>")
def amend_assessor(assessor_id):
    authenticate([ROLE_COORDINATOR])
    assessor = find_or_404("assessors", assessor_id, "ERR_ASSESSOR_NOT_FOUND")
    body = json_body()
    if present(body, "status"):
        assessor["status"] = as_enum(body["status"], "status", ASSESSOR_STATUSES)
    if present(body, "credential_rank"):
        assessor["credential_rank"] = as_int(body["credential_rank"], "credential_rank", 1, 3)
    if present(body, "max_concurrent_assignments"):
        assessor["max_concurrent_assignments"] = as_int(
            body["max_concurrent_assignments"], "max_concurrent_assignments", 1, 10)
    if present(body, "appeal_panel_member"):
        assessor["appeal_panel_member"] = as_bool(body["appeal_panel_member"], "appeal_panel_member")
    if present(body, "department_code"):
        assessor["department_code"] = as_str(body["department_code"], "department_code", 2, 8, r"^[A-Z0-9]{2,8}$")
    touch(assessor)
    return ok(assessor_out(assessor))
