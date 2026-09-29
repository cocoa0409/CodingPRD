"""Student endpoints (PRD 3.4) plus the two student-scoped reads."""

from flask import Blueprint

from auth import (ROLE_BURSAR, ROLE_COMPLIANCE, ROLE_PROGRAM_ADMIN,
                  ROLE_REGISTRAR, ROLE_STUDENT, authenticate)
from domain import (charge_json, enrollment_json, get_student, ledger_json,
                    ledger_of_student, student_json)
from errors import fail
from response import apply_filters, object_response, paginate
from store import base_record, db, in_order
from validate import f_str, get_body

bp = Blueprint("students", __name__)


@bp.post("/students")
def create_student():
    authenticate(ROLE_REGISTRAR)
    body = get_body(("external_id", "full_name", "email", "program_code"))
    external_id = f_str(body, "external_id")
    full_name = f_str(body, "full_name")
    email = f_str(body, "email")
    program_code = f_str(body, "program_code")

    for existing in db.students.values():
        if existing["external_id"] == external_id:
            fail("ERR_DUPLICATE_RESOURCE_KEY")

    student = base_record()
    student.update({
        "external_id": external_id,
        "full_name": full_name,
        "email": email,
        "program_code": program_code,
        "status": "ACTIVE",
    })
    db.students[student["id"]] = student
    return object_response(student_json(student), 201)


@bp.get("/students/<student_id>")
def read_student(student_id):
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_REGISTRAR, ROLE_BURSAR, ROLE_COMPLIANCE,
                 ROLE_STUDENT)
    return object_response(student_json(get_student(student_id)))


@bp.get("/students")
def list_students():
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_REGISTRAR, ROLE_BURSAR)
    items = apply_filters(in_order(db.students.values()),
                          [("external_id", "external_id"), ("status", "status")])
    return paginate(items, student_json)


@bp.get("/students/<student_id>/enrollments")
def list_student_enrollments(student_id):
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_REGISTRAR, ROLE_BURSAR, ROLE_STUDENT)
    student = get_student(student_id)
    items = in_order([e for e in db.enrollments.values()
                      if e["student_id"] == student["id"]])
    items = apply_filters(items, [("status", "status")])
    return paginate(items, enrollment_json)


@bp.get("/students/<student_id>/charges")
def list_student_charges(student_id):
    authenticate(ROLE_PROGRAM_ADMIN, ROLE_REGISTRAR, ROLE_BURSAR, ROLE_STUDENT)
    student = get_student(student_id)
    items = in_order([c for c in db.charges.values()
                      if c["student_id"] == student["id"]])
    items = apply_filters(items, [("billing_status", "billing_status")])
    return paginate(items, charge_json)


@bp.get("/students/<student_id>/ledger-entries")
def list_student_ledger(student_id):
    actor = authenticate(ROLE_PROGRAM_ADMIN, ROLE_BURSAR, ROLE_STUDENT)
    student = get_student(student_id)
    if actor.role == ROLE_STUDENT and actor.user_id != student["id"]:
        fail("ERR_NOT_RESOURCE_OWNER")
    items = apply_filters(ledger_of_student(student["id"]),
                          [("entry_type", "entry_type")])
    return paginate(items, ledger_json)
