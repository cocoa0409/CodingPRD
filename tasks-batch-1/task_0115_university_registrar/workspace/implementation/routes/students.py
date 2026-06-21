"""Student routes: create, get, reverse-reachability lists, transcript,
and degree audit."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, request

import db
from middleware import authenticate, parse_pagination, require_roles
from response import ok_array, ok_object
from services import core, helpers as h
from services import serialize
from services.entities import new_common

bp = Blueprint("students", __name__)

ALL_ROLES = ("Registrar", "Advisor", "Student", "Bursar")


@bp.post("/students")
def create_student():
    authenticate()
    require_roles("Registrar")
    body = h.get_json_body()

    full_name = h.require_string(body, "full_name")
    email = h.require_string(body, "email")
    program_id = h.require_string(body, "program_id")
    completed_credit_hours = h.optional_int(body, "completed_credit_hours", 0)
    h.get_program(program_id)

    rec = new_common("Student")
    rec.update({
        "full_name": full_name,
        "email": email,
        "program_id": program_id,
        "completed_credit_hours": completed_credit_hours,
        "earned_credit_hours": completed_credit_hours,
        "gpa": 0.00,
        "academic_standing": "GOOD",
        "tuition_owed_cents": 0,
    })
    db.students[rec["id"]] = rec
    return ok_object(serialize.student(rec), 201)


@bp.get("/students/<student_id>")
def get_student(student_id):
    authenticate()
    require_roles(*ALL_ROLES)
    rec = h.get_student(student_id)
    return ok_object(serialize.student(rec), 200)


@bp.get("/students/<student_id>/enrollments")
def list_student_enrollments(student_id):
    authenticate()
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    h.get_student(student_id)

    term_id = request.args.get("term_id")
    registration_status = request.args.get("registration_status")
    recs = [
        e for e in db.enrollments.values()
        if e["student_id"] == student_id
        and (term_id is None or e["term_id"] == term_id)
        and (registration_status is None or e["registration_status"] == registration_status)
    ]
    recs = h.order_by_created(recs)
    page, total = h.paginate(recs, limit, offset)
    return ok_array([serialize.enrollment(e) for e in page], limit, offset, total, 200)


@bp.get("/students/<student_id>/holds")
def list_student_holds(student_id):
    authenticate()
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    h.get_student(student_id)

    status = request.args.get("status")
    recs = [
        ho for ho in db.holds.values()
        if ho["student_id"] == student_id
        and (status is None or ho["status"] == status)
    ]
    recs = h.order_by_created(recs)
    page, total = h.paginate(recs, limit, offset)
    return ok_array([serialize.hold(ho) for ho in page], limit, offset, total, 200)


@bp.get("/students/<student_id>/appointments")
def list_student_appointments(student_id):
    authenticate()
    require_roles("Registrar", "Advisor", "Student")
    limit, offset = parse_pagination()
    h.get_student(student_id)

    term_id = request.args.get("term_id")
    recs = [
        a for a in db.appointments.values()
        if a["student_id"] == student_id
        and (term_id is None or a["term_id"] == term_id)
    ]
    recs = h.order_by_created(recs)
    page, total = h.paginate(recs, limit, offset)
    return ok_array([serialize.appointment(a) for a in page], limit, offset, total, 200)


@bp.get("/students/<student_id>/swap-requests")
def list_student_swap_requests(student_id):
    authenticate()
    require_roles("Registrar", "Advisor", "Student")
    limit, offset = parse_pagination()
    h.get_student(student_id)

    term_id = request.args.get("term_id")
    status = request.args.get("status")
    recs = [
        sr for sr in db.swap_requests.values()
        if sr["student_id"] == student_id
        and (term_id is None or sr["term_id"] == term_id)
        and (status is None or sr["status"] == status)
    ]
    recs = h.order_by_created(recs)
    page, total = h.paginate(recs, limit, offset)
    return ok_array([serialize.swap_request(sr) for sr in page], limit, offset, total, 200)


@bp.get("/students/<student_id>/refunds")
def list_student_refunds(student_id):
    authenticate()
    require_roles("Registrar", "Bursar", "Student")
    limit, offset = parse_pagination()
    h.get_student(student_id)

    recs = [
        rt for rt in db.refund_transactions.values()
        if rt["student_id"] == student_id
    ]
    recs = h.order_by_created(recs)
    page, total = h.paginate(recs, limit, offset)
    return ok_array([serialize.refund_transaction(rt) for rt in page], limit, offset, total, 200)


def _gpa_over(enrollments):
    """Credit-hour-weighted GPA over a set of graded, A-F enrollments."""
    considered = [
        e for e in enrollments
        if e["grade_status"] == "GRADED" and e["letter_grade"] in core.GRADE_POINTS
    ]
    total_quality = Decimal(0)
    total_credits = 0
    for e in considered:
        ch = db.courses[db.sections[e["section_id"]]["course_id"]]["credit_hours"]
        total_quality += Decimal(str(core.GRADE_POINTS[e["letter_grade"]])) * Decimal(ch)
        total_credits += ch
    if total_credits == 0:
        return 0.00
    return core.round_half_up_2dp(total_quality / Decimal(total_credits))


@bp.get("/students/<student_id>/transcript")
def transcript(student_id):
    authenticate()
    require_roles(*ALL_ROLES)
    student = h.get_student(student_id)
    term_id = request.args.get("term_id")
    if term_id is not None:
        h.get_term(term_id)

    all_enr = core.student_enrollments(student_id)
    graded = [
        e for e in all_enr
        if e["grade_status"] == "GRADED" and e["letter_grade"] in core.GRADE_POINTS
    ]

    cumulative_gpa = _gpa_over(all_enr)
    if term_id is not None:
        term_set = [e for e in all_enr if e["term_id"] == term_id]
        term_gpa = _gpa_over(term_set)
        lines_src = [e for e in graded if e["term_id"] == term_id]
    else:
        term_gpa = cumulative_gpa
        lines_src = graded

    lines_src = h.order_by_created(lines_src)
    lines = [serialize.enrollment(e) for e in lines_src]

    data = {
        "cumulative_gpa": cumulative_gpa,
        "term_gpa": term_gpa,
        "earned_credit_hours": student["earned_credit_hours"],
        "lines": lines,
    }
    return ok_object(data, 200)


@bp.get("/students/<student_id>/degree-audit")
def degree_audit(student_id):
    authenticate()
    require_roles("Registrar", "Advisor", "Student")
    student = h.get_student(student_id)
    program = db.programs[student["program_id"]]

    earned = student["earned_credit_hours"]
    required = program["required_credit_hours"]
    credits_remaining = max(0, required - earned)
    gpa_ok = student["gpa"] >= program["min_gpa"]
    is_complete = (credits_remaining == 0) and gpa_ok

    # satisfied courses: graded enrollment with letter in {A,B,C,D} (D or better)
    satisfied = set()
    for e in core.student_enrollments(student_id):
        if e["grade_status"] == "GRADED" and e["letter_grade"] in core.PASSING_GRADE_LETTERS:
            satisfied.add(db.sections[e["section_id"]]["course_id"])

    data = {
        "required_credit_hours": required,
        "earned_credit_hours": earned,
        "credits_remaining": credits_remaining,
        "gpa_ok": gpa_ok,
        "is_complete": is_complete,
        "satisfied_course_ids": sorted(satisfied),
    }
    return ok_object(data, 200)
