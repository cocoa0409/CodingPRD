"""Term enrollments, registration, and reduced course loads (PRD §3.3, §3.4)."""

import math
from datetime import timedelta

from flask import Blueprint, request

import db
import services
from db import clock_date, new_id, parse_date, stamp_new, touch
from errors import (
    ERR_ADD_DROP_CLOSED,
    ERR_BELOW_FULL_COURSE_LOAD,
    ERR_DUPLICATE_ENROLLMENT,
    ERR_ENROLLMENT_NOT_REGISTERABLE,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_RCL_ADD_DROP_CLOSED,
    ERR_RCL_ALREADY_OPEN,
    ERR_RCL_CREDITS_OUT_OF_RANGE,
    ERR_RCL_NOT_FINAL_TERM,
    ERR_RCL_NOT_REQUESTED,
    ERR_RCL_REASON_EXHAUSTED,
    ERR_RECORD_NOT_ACTIVE,
    ERR_REGISTRATION_DEADLINE_PASSED,
    ERR_RESOURCE_NOT_OWNED,
    raise_error,
)
from helpers import (
    body, get_or_404, get_student_or_404, list_response, opt_str, req_date,
    req_enum, req_int, req_str,
)
from middleware import ALL_ROLES, STAFF_ROLES, require_roles
from response import success_object
from serializers import reduced_course_load_out, term_enrollment_out

bp = Blueprint("enrollments", __name__)

RCL_REASONS = ("ACADEMIC", "MEDICAL", "FINAL_TERM")
RCL_DECISIONS = ("APPROVED", "DENIED")


def _check_enrollment_scope(user_id, role, enrollment):
    if role == "Student" and enrollment["student_id"] != user_id:
        raise_error(ERR_RESOURCE_NOT_OWNED, "Students may only act on their own resources")


# ---------------------------------------------------------------------------
# Term enrollments
# ---------------------------------------------------------------------------

@bp.route("/sevis/term-enrollments", methods=["POST"])
def create_enrollment():
    require_roles(STAFF_ROLES)
    data = body()
    student_id = req_str(data, "student_id")
    term_code = req_str(data, "term_code")
    term_start_date = req_date(data, "term_start_date")
    term_end_date = req_date(data, "term_end_date")
    enrolled_credits = req_int(data, "enrolled_credits", min_value=0)
    if parse_date(term_end_date) <= parse_date(term_start_date):
        raise_error(ERR_INVALID_REQUEST, "term_end_date must be later than term_start_date")
    student = get_student_or_404(student_id)
    for existing in db.term_enrollments.values():
        if existing["student_id"] == student["id"] and existing["term_code"] == term_code:
            raise_error(ERR_DUPLICATE_ENROLLMENT, "An enrollment for this student_id + term_code already exists")
    enrollment = {
        "id": new_id(),
        "student_id": student["id"],
        "term_code": term_code,
        "term_start_date": term_start_date,
        "term_end_date": term_end_date,
        "enrolled_credits": enrolled_credits,
        "effective_min_credits": services.base_min_credits(student),
        "status": "PENDING",
    }
    stamp_new(enrollment)
    db.term_enrollments[enrollment["id"]] = enrollment
    return success_object(term_enrollment_out(enrollment), 201)


@bp.route("/sevis/term-enrollments", methods=["GET"])
def list_enrollments():
    user_id, role = require_roles(ALL_ROLES)
    student_filter = request.args.get("student_id")
    if role == "Student":
        if student_filter is not None and student_filter != user_id:
            raise_error(ERR_RESOURCE_NOT_OWNED, "Students may only list their own resources")
        student_filter = user_id
    filters = {
        "student_id": student_filter,
        "term_code": request.args.get("term_code"),
        "status": request.args.get("status"),
    }
    return list_response(list(db.term_enrollments.values()), term_enrollment_out, filters)


@bp.route("/sevis/term-enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    user_id, role = require_roles(ALL_ROLES)
    enrollment = get_or_404(db.term_enrollments, eid, "TermEnrollment")
    _check_enrollment_scope(user_id, role, enrollment)
    return success_object(term_enrollment_out(enrollment), 200)


@bp.route("/sevis/term-enrollments/<eid>", methods=["PATCH"])
def patch_enrollment(eid):
    user_id, role = require_roles(ALL_ROLES)
    enrollment = get_or_404(db.term_enrollments, eid, "TermEnrollment")
    _check_enrollment_scope(user_id, role, enrollment)
    data = body()
    new_credits = req_int(data, "enrolled_credits", min_value=0)
    if enrollment["status"] not in ("PENDING", "REGISTERED"):
        raise_error(ERR_ENROLLMENT_NOT_REGISTERABLE, "Enrollment must be PENDING or REGISTERED to edit credits")
    if enrollment["status"] == "REGISTERED":
        add_drop_close = parse_date(enrollment["term_start_date"]) + timedelta(days=services.ADD_DROP_DAYS)
        if clock_date() > add_drop_close:
            raise_error(ERR_ADD_DROP_CLOSED, "Add/drop closed for this enrollment")
    if services.approved_rcl_of(enrollment["id"]) is None \
            and new_credits < enrollment["effective_min_credits"]:
        raise_error(ERR_BELOW_FULL_COURSE_LOAD, "enrolled_credits below effective_min_credits without an APPROVED RCL")
    enrollment["enrolled_credits"] = new_credits
    touch(enrollment)
    return success_object(term_enrollment_out(enrollment), 200)


@bp.route("/sevis/term-enrollments/<eid>/register", methods=["POST"])
def register_enrollment(eid):
    require_roles(STAFF_ROLES)
    enrollment = get_or_404(db.term_enrollments, eid, "TermEnrollment")
    if enrollment["status"] != "PENDING":
        raise_error(ERR_ENROLLMENT_NOT_REGISTERABLE, "Enrollment must be PENDING to register")
    record = services.record_of_student(enrollment["student_id"])
    if record is None or record["status"] not in ("INITIAL", "ACTIVE"):
        raise_error(ERR_RECORD_NOT_ACTIVE, "Record must be INITIAL or ACTIVE to register")
    deadline = parse_date(enrollment["term_start_date"]) + timedelta(days=services.REGISTRATION_WINDOW_DAYS)
    if clock_date() > deadline:
        raise_error(ERR_REGISTRATION_DEADLINE_PASSED, "Registration deadline (term_start_date + 30 days) has passed")
    if enrollment["enrolled_credits"] < enrollment["effective_min_credits"]:
        raise_error(ERR_BELOW_FULL_COURSE_LOAD, "enrolled_credits below effective_min_credits")
    enrollment["status"] = "REGISTERED"
    touch(enrollment)
    if record["status"] == "INITIAL":
        record["status"] = "ACTIVE"
        touch(record)
    return success_object(term_enrollment_out(enrollment), 200)


# ---------------------------------------------------------------------------
# Reduced course loads (PRD §3.4)
# ---------------------------------------------------------------------------

@bp.route("/sevis/reduced-course-loads", methods=["POST"])
def create_rcl():
    require_roles(STAFF_ROLES)
    data = body()
    enrollment_id = req_str(data, "enrollment_id")
    reason_category = req_enum(data, "reason_category", RCL_REASONS)
    requested_credits = req_int(data, "requested_credits", min_value=0)
    enrollment = get_or_404(db.term_enrollments, enrollment_id, "TermEnrollment")
    student = get_student_or_404(enrollment["student_id"])

    # State (priority 4/5): parent enrollment must be PENDING or REGISTERED.
    if enrollment["status"] not in ("PENDING", "REGISTERED"):
        raise_error(ERR_ENROLLMENT_NOT_REGISTERABLE, "Parent enrollment must be PENDING or REGISTERED")
    # Uniqueness (priority 6): at most one open (REQUESTED/APPROVED) RCL per enrollment.
    for existing in db.reduced_course_loads.values():
        if existing["enrollment_id"] == enrollment["id"] and existing["status"] in ("REQUESTED", "APPROVED"):
            raise_error(ERR_RCL_ALREADY_OPEN, "Enrollment already has a REQUESTED or APPROVED RCL")
    # Temporal (priority 7): add/drop close, then FINAL_TERM containment.
    add_drop_close = parse_date(enrollment["term_start_date"]) + timedelta(days=services.ADD_DROP_DAYS)
    if clock_date() > add_drop_close:
        raise_error(ERR_RCL_ADD_DROP_CLOSED, "RCL requested after term_start_date + 14 days")
    base = services.base_min_credits(student)
    if reason_category == "FINAL_TERM":
        record = services.record_of_student(student["id"])
        in_window = (
            record is not None
            and parse_date(enrollment["term_start_date"]) <= parse_date(record["program_end_date"])
            <= parse_date(enrollment["term_end_date"])
        )
        if not in_window:
            raise_error(ERR_RCL_NOT_FINAL_TERM, "FINAL_TERM RCL term window must contain program_end_date")
    # Credit rules (priority 9): category range first, then reason exhaustion.
    if reason_category == "ACADEMIC":
        if requested_credits < services.academic_floor(base):
            raise_error(ERR_RCL_CREDITS_OUT_OF_RANGE, "ACADEMIC requested_credits below the academic floor")
    elif reason_category == "FINAL_TERM":
        if requested_credits >= base:
            raise_error(ERR_RCL_CREDITS_OUT_OF_RANGE, "FINAL_TERM requested_credits must be below the base full-time minimum")
    if reason_category == "ACADEMIC":
        for other in db.reduced_course_loads.values():
            if other["reason_category"] != "ACADEMIC" or other["status"] not in ("REQUESTED", "APPROVED"):
                continue
            other_enrollment = db.term_enrollments.get(other["enrollment_id"])
            if other_enrollment is not None and other_enrollment["student_id"] == student["id"]:
                raise_error(ERR_RCL_REASON_EXHAUSTED, "ACADEMIC RCL already used at this program level")
    elif reason_category == "MEDICAL":
        total_months = 0
        for other in db.reduced_course_loads.values():
            if other["reason_category"] != "MEDICAL" or other["status"] not in ("REQUESTED", "APPROVED"):
                continue
            other_enrollment = db.term_enrollments.get(other["enrollment_id"])
            if other_enrollment is None or other_enrollment["student_id"] != student["id"]:
                continue
            span_days = (parse_date(other_enrollment["term_end_date"]) - parse_date(other_enrollment["term_start_date"])).days
            total_months += math.ceil(span_days / services.DAYS_PER_MONTH)
        new_days = (parse_date(enrollment["term_end_date"]) - parse_date(enrollment["term_start_date"])).days
        if total_months + math.ceil(new_days / services.DAYS_PER_MONTH) > services.MEDICAL_CUMULATIVE_MONTHS_MAX:
            raise_error(ERR_RCL_REASON_EXHAUSTED, "MEDICAL RCL cumulative months would exceed 12")

    rcl = {
        "id": new_id(),
        "enrollment_id": enrollment["id"],
        "reason_category": reason_category,
        "requested_credits": requested_credits,
        "status": "REQUESTED",
        "decision_note": None,
    }
    stamp_new(rcl)
    db.reduced_course_loads[rcl["id"]] = rcl
    return success_object(reduced_course_load_out(rcl), 201)


@bp.route("/sevis/term-enrollments/<eid>/reduced-course-loads", methods=["GET"])
def list_rcls(eid):
    user_id, role = require_roles(ALL_ROLES)
    enrollment = get_or_404(db.term_enrollments, eid, "TermEnrollment")
    _check_enrollment_scope(user_id, role, enrollment)
    items = [r for r in db.reduced_course_loads.values() if r["enrollment_id"] == enrollment["id"]]
    return list_response(items, reduced_course_load_out)


@bp.route("/sevis/reduced-course-loads/<rid>/decision", methods=["POST"])
def decide_rcl(rid):
    require_roles(STAFF_ROLES)
    rcl = get_or_404(db.reduced_course_loads, rid, "ReducedCourseLoad")
    data = body()
    decision = req_enum(data, "decision", RCL_DECISIONS)
    note = opt_str(data, "note")
    if rcl["status"] != "REQUESTED":
        raise_error(ERR_RCL_NOT_REQUESTED, "RCL not in REQUESTED for decision")
    if decision == "APPROVED":
        enrollment = db.term_enrollments.get(rcl["enrollment_id"])
        if enrollment is None or enrollment["status"] not in ("PENDING", "REGISTERED"):
            raise_error(ERR_ENROLLMENT_NOT_REGISTERABLE, "Parent enrollment must be PENDING or REGISTERED for approval")
        rcl["status"] = "APPROVED"
        # Approval recomputes the parent enrollment's effective floor.
        enrollment["effective_min_credits"] = services.effective_min_credits(enrollment)
        touch(enrollment)
    else:
        rcl["status"] = "DENIED"
    if note is not None:
        rcl["decision_note"] = note
    touch(rcl)
    return success_object(reduced_course_load_out(rcl), 200)
