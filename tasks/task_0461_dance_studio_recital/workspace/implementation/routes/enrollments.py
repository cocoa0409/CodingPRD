"""Enrollment routes (PRD 3.3, 3.4, 3.5)."""
from datetime import timedelta

from flask import Blueprint, request

from db import common_fields, db, new_id, touch
from errors import err
from helpers import (LEVEL_ORDINAL, MAKEUP_WINDOW_DAYS, lookup, paginate,
                     parse_date, sort_by_created)
from middleware import authenticate, get_json, require_owner
from response import success
from routes.students import age_as_of
from services.enrollment import (confirm_enrollment, drop_enrollment,
                                 effective_capacity, waitlist_enrollment)
from services.tuition import recompute_family
from views import public, public_list

bp = Blueprint("enrollments", __name__)


def _recompute_age_against_term(student, term):
    """Recompute and store age_as_of_cutoff against a term (PRD 3.3)."""
    cutoff = parse_date(term, "age_cutoff_date")
    birth = student.get("_birth")
    if birth is None:
        birth = parse_date(student, "birth_date")
        student["_birth"] = birth
    age = age_as_of(birth, cutoff)
    if student["age_as_of_cutoff"] != age:
        student["age_as_of_cutoff"] = age
        touch(student)
    return age


def _check_eligibility(student, section, age):
    """Level check before age check (PRD 3.3)."""
    if LEVEL_ORDINAL[student["level"]] < LEVEL_ORDINAL[section["required_level"]]:
        raise err("ERR_LEVEL_TOO_LOW", "Student level below the section's required level.")
    if not (section["min_age"] <= age <= section["max_age"]):
        raise err("ERR_AGE_OUT_OF_BAND", "Student age outside the section band.")


def _validate_makeup(att_id, section, student):
    """Makeup placement eligibility (PRD 3.5). Returns the cited attendance."""
    att = lookup(db.attendance, att_id)
    eligible = att["result"] == "ABSENT_EXCUSED" and not att["makeup_consumed"]
    if not eligible:
        raise err("ERR_MAKEUP_INELIGIBLE", "Cited attendance is not makeup-eligible.")
    # occurred_on must be within MAKEUP_WINDOW_DAYS immediately preceding the
    # makeup session's date (the logical clock date stands in as the makeup date).
    occurred = parse_date(att, "occurred_on")
    makeup_date = db.clock.date()
    window_start = makeup_date - timedelta(days=MAKEUP_WINDOW_DAYS)
    if not (window_start <= occurred <= makeup_date):
        raise err("ERR_MAKEUP_INELIGIBLE", "Cited absence is outside the makeup window.")
    return att


@bp.route("/enrollments", methods=["POST"])
def create_enrollment():
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    body = get_json()
    if "student_id" not in body or body["student_id"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: student_id.")
    if "section_id" not in body or body["section_id"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: section_id.")
    student = lookup(db.students, body["student_id"])
    require_owner(role, user_id, student["family_id"])
    section = lookup(db.sections, body["section_id"])

    makeup_att = None
    if body.get("makeup_for_attendance_id"):
        makeup_att = _validate_makeup(body["makeup_for_attendance_id"], section, student)

    term = db.terms.get(section["term_id"])
    age = _recompute_age_against_term(student, term) if term else student["age_as_of_cutoff"]
    _check_eligibility(student, section, age)

    family = db.families.get(student["family_id"])

    enr = {
        "id": new_id(),
        "student_id": student["id"],
        "section_id": section["id"],
        "family_id": student["family_id"],
        "placement_status": "PENDING",
        "billing_status": "UNBILLED",
        "waitlist_rank": 0,
        "monthly_charge_cents": 0,
        **common_fields(),
    }
    if makeup_att is not None:
        enr["makeup_for_attendance_id"] = body["makeup_for_attendance_id"]
    db.enrollments[enr["id"]] = enr

    # Auto-resolve placement.
    if section["status"] == "OPEN" and section["enrolled_count"] < effective_capacity(section):
        # Confirmation additionally requires the family not be DELINQUENT.
        if family is not None and family["status"] == "DELINQUENT":
            raise err("ERR_FAMILY_DELINQUENT", "Delinquent family cannot confirm enrollment.")
        confirm_enrollment(enr, section)
    elif section["status"] == "FULL":
        waitlist_enrollment(enr, section)
    else:
        # Section not OPEN (and not FULL) -> cannot confirm; remains PENDING.
        # A non-enrollable section state is an invalid placement target.
        raise err("ERR_INVALID_STATE", "Section is not open for enrollment.")

    if makeup_att is not None:
        makeup_att["makeup_consumed"] = True
        makeup_att["makeup_eligible"] = False

    return success(public(enr), status=201)


@bp.route("/enrollments/<eid>", methods=["GET"])
def get_enrollment(eid):
    user_id, role = authenticate({"StudioAdmin", "Parent", "Instructor"})
    enr = lookup(db.enrollments, eid)
    require_owner(role, user_id, enr["family_id"])
    return success(public(enr), status=200)


@bp.route("/enrollments", methods=["GET"])
def list_enrollments():
    authenticate({"StudioAdmin", "Parent", "Instructor"})
    items = list(db.enrollments.values())
    for key in ("section_id", "student_id", "family_id"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e[key] == val]
    items = sort_by_created(items)
    page, pg = paginate(items)
    return success(public_list(page), status=200, is_array=True, pagination=pg)


@bp.route("/enrollments/<eid>/confirm", methods=["POST"])
def confirm_enrollment_route(eid):
    authenticate({"StudioAdmin"})
    enr = lookup(db.enrollments, eid)
    if enr["placement_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Enrollment is not PENDING.")
    section = db.sections.get(enr["section_id"])
    student = db.students.get(enr["student_id"])
    if section is None or student is None:
        raise err("ERR_NOT_FOUND", "Enrollment references a missing resource.")
    if section["status"] not in {"OPEN", "FULL"}:
        raise err("ERR_INVALID_STATE", "Section is not open for enrollment.")
    term = db.terms.get(section["term_id"])
    age = _recompute_age_against_term(student, term) if term else student["age_as_of_cutoff"]
    _check_eligibility(student, section, age)
    # Capacity guard on the explicit confirm path.
    if section["enrolled_count"] >= effective_capacity(section):
        raise err("ERR_CAPACITY_EXCEEDED", "Section is already at effective capacity.")
    family = db.families.get(enr["family_id"])
    if family is not None and family["status"] == "DELINQUENT":
        raise err("ERR_FAMILY_DELINQUENT", "Delinquent family cannot confirm enrollment.")
    confirm_enrollment(enr, section)
    return success(public(enr), status=200)


@bp.route("/enrollments/<eid>/drop", methods=["POST"])
def drop_enrollment_route(eid):
    user_id, role = authenticate({"StudioAdmin", "Parent"})
    enr = lookup(db.enrollments, eid)
    require_owner(role, user_id, enr["family_id"])
    if enr["placement_status"] not in {"CONFIRMED", "WAITLISTED", "WAITLIST_PROMOTED"}:
        raise err("ERR_INVALID_STATE", "Enrollment cannot be dropped.")
    drop_enrollment(enr)
    return success(public(enr), status=200)


@bp.route("/enrollments/<eid>/pause-billing", methods=["POST"])
def pause_billing(eid):
    authenticate({"StudioAdmin"})
    enr = lookup(db.enrollments, eid)
    if enr["placement_status"] != "CONFIRMED" or enr["billing_status"] != "BILLING_ACTIVE":
        raise err("ERR_INVALID_STATE", "Enrollment is not billing-active.")
    enr["billing_status"] = "BILLING_PAUSED"
    touch(enr)
    recompute_family(enr["family_id"])
    return success(public(enr), status=200)


@bp.route("/enrollments/<eid>/resume-billing", methods=["POST"])
def resume_billing(eid):
    authenticate({"StudioAdmin"})
    enr = lookup(db.enrollments, eid)
    if enr["placement_status"] != "CONFIRMED" or enr["billing_status"] != "BILLING_PAUSED":
        raise err("ERR_INVALID_STATE", "Enrollment is not billing-paused.")
    enr["billing_status"] = "BILLING_ACTIVE"
    touch(enr)
    recompute_family(enr["family_id"])
    return success(public(enr), status=200)
