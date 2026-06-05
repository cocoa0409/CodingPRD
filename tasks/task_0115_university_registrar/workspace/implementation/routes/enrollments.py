"""Enrollment routes: register, get, drop, withdraw, grade, list refunds."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import err
from middleware import authenticate, current_user_id, parse_pagination, require_roles
from response import ok_array, ok_object
from services import enroll, helpers as h
from services import serialize

bp = Blueprint("enrollments", __name__)

ALL_ROLES = ("Registrar", "Advisor", "Student", "Bursar")


@bp.post("/enrollments")
def create_enrollment():
    authenticate()
    require_roles("Student")
    body = h.get_json_body()

    # Body well-formedness (priority 2.5).
    term_id = h.require_string(body, "term_id")
    section_id = h.require_string(body, "section_id")
    expected_section_version = h.require_int(body, "expected_section_version")

    # Existence (priority 3), left-to-right: Term, Student (acting), Section.
    term = h.get_term(term_id)
    student_id = current_user_id()
    h.get_student(student_id)  # acting Student must exist
    section = h.get_section(section_id)

    # Ownership (priority 4): the enrollment's student_id is the acting student,
    # so X-User-ID == student_id by construction; no mismatch is possible.

    rec = enroll.register(student_id, term, section, expected_section_version)
    return ok_object(serialize.enrollment(rec), 201)


@bp.get("/enrollments/<enrollment_id>")
def get_enrollment(enrollment_id):
    authenticate()
    require_roles(*ALL_ROLES)
    rec = h.get_enrollment(enrollment_id)
    return ok_object(serialize.enrollment(rec), 200)


def _owned_enrollment(enrollment_id: str):
    """Fetch an enrollment and enforce student ownership (priority 4)."""
    rec = h.get_enrollment(enrollment_id)
    if rec["student_id"] != current_user_id():
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting Student does not own this enrollment")
    return rec


@bp.post("/enrollments/<enrollment_id>/drop")
def drop_enrollment(enrollment_id):
    authenticate()
    require_roles("Student")
    rec = _owned_enrollment(enrollment_id)
    rec = enroll.drop(rec)
    return ok_object(serialize.enrollment(rec), 200)


@bp.post("/enrollments/<enrollment_id>/withdraw")
def withdraw_enrollment(enrollment_id):
    authenticate()
    require_roles("Student")
    rec = _owned_enrollment(enrollment_id)
    rec = enroll.withdraw(rec)
    return ok_object(serialize.enrollment(rec), 200)


@bp.post("/enrollments/<enrollment_id>/grade")
def grade_enrollment(enrollment_id):
    authenticate()
    require_roles("Advisor")
    body = h.get_json_body()
    # letter_grade must be present as a string (else ERR_VALIDATION for missing/
    # wrong type); an out-of-set letter is rejected with ERR_INVALID_GRADE inside
    # the grade service per PRD §3.8 / validation priority 19.
    letter_grade = h.require_string(body, "letter_grade")

    rec = h.get_enrollment(enrollment_id)
    rec = enroll.grade(rec, letter_grade)
    return ok_object(serialize.enrollment(rec), 200)


@bp.get("/enrollments/<enrollment_id>/refunds")
def list_enrollment_refunds(enrollment_id):
    authenticate()
    require_roles("Registrar", "Bursar", "Student")
    limit, offset = parse_pagination()
    h.get_enrollment(enrollment_id)

    recs = [
        rt for rt in db.refund_transactions.values()
        if rt["enrollment_id"] == enrollment_id
    ]
    recs = h.order_by_created(recs)
    page, total = h.paginate(recs, limit, offset)
    return ok_array([serialize.refund_transaction(rt) for rt in page], limit, offset, total, 200)
