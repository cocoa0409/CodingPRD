"""Student (electorate register) endpoints (PRD 3.1).

The registrar sync is not inert: amending class_year, enrollment_status, gpa,
credits_completed or disciplinary_hold re-evaluates the eligibility verdict on
every signature the student has given.  It never moves a frozen electorate size.
"""
from flask import Blueprint

import auth
import calc
import constants
import db
import errors
import listing
import lookup
import response
import serialize
import validation

bp = Blueprint("students", __name__)


@bp.post("/students")
def create_student():
    auth.require(constants.REGISTRAR)
    body = validation.get_body()

    full_name = validation.req_str(body, "full_name")
    student_number = validation.req_str(body, "student_number", min_len=1, max_len=32)
    class_year = validation.req_enum(body, "class_year", constants.CLASS_YEARS)
    gpa = validation.req_decimal(body, "gpa", minimum=0, maximum=4)
    enrollment_status = validation.opt_enum(body, "enrollment_status",
                                            constants.ENROLLMENT_STATUSES,
                                            default="ENROLLED")
    credits_completed = validation.opt_int(body, "credits_completed", default=0, minimum=0)
    disciplinary_hold = validation.opt_bool(body, "disciplinary_hold", default=False)

    for existing in db.store.students.values():
        if existing["student_number"] == student_number:
            errors.fail(errors.ERR_INVALID_REQUEST,
                        "student_number must be unique across the register.")

    row = db.new_row(db.store.students, {
        "full_name": full_name,
        "student_number": student_number,
        "class_year": class_year,
        "enrollment_status": enrollment_status,
        "gpa": gpa,
        "credits_completed": credits_completed,
        "disciplinary_hold": disciplinary_hold,
    })
    return response.object_response(serialize.student(row), 201)


@bp.get("/students")
def list_students():
    auth.require_any()
    rows = listing.filtered(db.store.students, {
        "class_year": ("class_year", None),
        "enrollment_status": ("enrollment_status", None),
    })
    return listing.list_response(rows, serialize.student)


@bp.get("/students/<student_id>")
def read_student(student_id):
    auth.require_any()
    row = lookup.student(student_id)
    return response.object_response(serialize.student(row))


@bp.patch("/students/<student_id>")
def sync_student(student_id):
    auth.require(constants.REGISTRAR)
    student = lookup.student(student_id)
    body = validation.get_body()

    updates = {}
    if validation.has_key(body, "class_year"):
        updates["class_year"] = validation.req_enum(body, "class_year", constants.CLASS_YEARS)
    if validation.has_key(body, "enrollment_status"):
        updates["enrollment_status"] = validation.req_enum(
            body, "enrollment_status", constants.ENROLLMENT_STATUSES)
    if validation.has_key(body, "gpa"):
        updates["gpa"] = validation.req_decimal(body, "gpa", minimum=0, maximum=4)
    if validation.has_key(body, "credits_completed"):
        updates["credits_completed"] = validation.req_int(body, "credits_completed", minimum=0)
    if validation.has_key(body, "disciplinary_hold"):
        updates["disciplinary_hold"] = validation.req_bool(body, "disciplinary_hold")

    db.set_fields(student, **updates)
    db.touch(student)

    # every candidacy this student has signed is re-scored
    signed = []
    for signature in db.store.petition_signatures.values():
        if signature["signer_student_id"] != student["id"]:
            continue
        if signature["candidacy_id"] not in signed:
            signed.append(signature["candidacy_id"])
    for candidacy_id in signed:
        candidacy = db.store.candidacies.get(candidacy_id)
        if candidacy is not None:
            calc.recompute_petition_counters(candidacy)

    return response.object_response(serialize.student(student))
