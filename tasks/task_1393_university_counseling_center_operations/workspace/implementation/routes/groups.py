"""GroupProgram + GroupEnrollment endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_UNAUTHORIZED,
    ERR_RISK_BAND_VIOLATION,
    ERR_PROGRAM_NOT_OPEN,
)
from middleware import require_roles
from response import success_object, success_list
from services import domain
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_enum,
    require_int,
    require_string,
    require_ts,
    sort_by_created_at,
)

bp = Blueprint("groups", __name__)


@bp.route("/ucc/group-programs", methods=["POST"])
@require_roles("Counselor", "ClinicalDirector")
def create_program(_user_id: str, _role: str):
    body = get_json_body()
    title = require_string(body, "title")
    facilitator_id = require_string(body, "facilitator_id")
    capacity = require_int(body, "capacity", minimum=1)
    meeting_day = require_string(body, "meeting_day")
    starts_at = require_ts(body, "starts_at")
    weeks = require_int(body, "weeks", minimum=1, maximum=16)
    risk_band_ceiling = require_enum(body, "risk_band_ceiling", domain.GROUP_RISK_CEILINGS)

    if db.counselors.get(facilitator_id) is None:
        raise_err(ERR_NOT_FOUND, "facilitator_id does not resolve")

    program = {
        "title": title,
        "facilitator_id": facilitator_id,
        "capacity": capacity,
        "meeting_day": meeting_day,
        "starts_at": starts_at,
        "weeks": weeks,
        "risk_band_ceiling": risk_band_ceiling,
        "status": "DRAFT",
    }
    db.stamp_new(program)
    db.group_programs[program["id"]] = program
    return success_object(serialize(program), 201)


@bp.route("/ucc/group-programs/<program_id>", methods=["GET"])
@require_roles("FrontDesk", "Counselor", "TriageScreener", "ClinicalDirector", "Student")
def get_program(program_id: str, _user_id: str, _role: str):
    p = db.group_programs.get(program_id)
    if p is None:
        raise_err(ERR_NOT_FOUND, "GroupProgram id does not exist")
    return success_object(serialize(p))


@bp.route("/ucc/group-programs", methods=["GET"])
@require_roles("FrontDesk", "Counselor", "TriageScreener", "ClinicalDirector", "Student")
def list_programs(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.group_programs.values()))
    items = apply_filters(items, ["status", "facilitator_id"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/ucc/group-programs/<program_id>/publish", methods=["POST"])
@require_roles("Counselor", "ClinicalDirector")
def publish_program(program_id: str, _user_id: str, _role: str):
    p = db.group_programs.get(program_id)
    if p is None:
        raise_err(ERR_NOT_FOUND, "GroupProgram id does not exist")
    # Ownership: counselor must be facilitator
    if _role == "Counselor" and p.get("facilitator_id") != _user_id:
        raise_err(ERR_UNAUTHORIZED, "Counselor may only publish own programs")
    if p.get("status") != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Program is not DRAFT")
    if int(p.get("capacity", 0)) < 1:
        raise_err(ERR_INVALID_REQUEST, "capacity must be >= 1")
    p["status"] = "OPEN"
    db.touch(p)
    return success_object(serialize(p))


@bp.route("/ucc/group-programs/<program_id>/cancel", methods=["POST"])
@require_roles("Counselor", "ClinicalDirector")
def cancel_program(program_id: str, _user_id: str, _role: str):
    p = db.group_programs.get(program_id)
    if p is None:
        raise_err(ERR_NOT_FOUND, "GroupProgram id does not exist")
    if _role == "Counselor" and p.get("facilitator_id") != _user_id:
        raise_err(ERR_UNAUTHORIZED, "Counselor may only cancel own programs")
    if p.get("status") != "OPEN":
        raise_err(ERR_INVALID_STATE, "Program is not OPEN")
    p["status"] = "CANCELLED"
    db.touch(p)
    # Drop all ENROLLED / WAITLISTED enrollments.
    for enr in db.group_enrollments.values():
        if enr.get("program_id") == p["id"] and enr.get("status") in ("ENROLLED", "WAITLISTED"):
            enr["status"] = "DROPPED"
    return success_object(serialize(p))


@bp.route("/ucc/group-programs/<program_id>/enrollments", methods=["POST"])
@require_roles("FrontDesk", "Counselor")
def enroll(program_id: str, _user_id: str, _role: str):
    p = db.group_programs.get(program_id)
    if p is None:
        raise_err(ERR_NOT_FOUND, "GroupProgram id does not exist")
    body = get_json_body()
    student_id = require_string(body, "student_id")
    student = db.students.get(student_id)
    if student is None:
        raise_err(ERR_NOT_FOUND, "student_id does not resolve")

    # Clinical-safety gate (p6): band from latest intake; no intake = LOW.
    latest = None
    for a in db.intake_assessments.values():
        if a.get("student_id") != student_id:
            continue
        if latest is None or (a.get("created_at", ""), a.get("id", "")) > (
            latest.get("created_at", ""), latest.get("id", "")
        ):
            latest = a
    band = latest.get("risk_band") if latest else "LOW"

    # CRITICAL students are never group-eligible regardless of ceiling.
    if band == "CRITICAL":
        raise_err(ERR_RISK_BAND_VIOLATION, "CRITICAL students are never group-eligible")
    if domain.BAND_RANK.get(band, 0) > domain.BAND_RANK.get(p.get("risk_band_ceiling"), 0):
        raise_err(ERR_RISK_BAND_VIOLATION, "Student risk band exceeds program ceiling")

    # Program must be OPEN.
    if p.get("status") != "OPEN":
        raise_err(ERR_PROGRAM_NOT_OPEN, "GroupProgram is not OPEN")

    # Capacity check: over-capacity -> WAITLISTED.
    enrolled_count = sum(
        1
        for e in db.group_enrollments.values()
        if e.get("program_id") == p["id"] and e.get("status") == "ENROLLED"
    )
    status = "ENROLLED" if enrolled_count < int(p.get("capacity", 0)) else "WAITLISTED"
    enrollment = {
        "program_id": p["id"],
        "student_id": student_id,
        "status": status,
    }
    db.stamp_new_light(enrollment)
    db.group_enrollments[enrollment["id"]] = enrollment
    return success_object(serialize(enrollment), 201)


@bp.route("/ucc/group-enrollments/<enrollment_id>", methods=["GET"])
@require_roles("FrontDesk", "Counselor", "ClinicalDirector", "Student")
def get_enrollment(enrollment_id: str, _user_id: str, _role: str):
    e = db.group_enrollments.get(enrollment_id)
    if e is None:
        raise_err(ERR_NOT_FOUND, "GroupEnrollment id does not exist")
    return success_object(serialize(e))


@bp.route("/ucc/group-enrollments", methods=["GET"])
@require_roles("FrontDesk", "Counselor", "ClinicalDirector")
def list_enrollments(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.group_enrollments.values()))
    items = apply_filters(items, ["program_id", "student_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/ucc/group-enrollments/<enrollment_id>/drop", methods=["POST"])
@require_roles("Student", "FrontDesk")
def drop_enrollment(enrollment_id: str, _user_id: str, _role: str):
    e = db.group_enrollments.get(enrollment_id)
    if e is None:
        raise_err(ERR_NOT_FOUND, "GroupEnrollment id does not exist")
    # Ownership: Student must own enrollment; FrontDesk may drop any.
    if _role == "Student" and e.get("student_id") != _user_id:
        raise_err(ERR_UNAUTHORIZED, "Student may only drop own enrollment")
    if e.get("status") != "ENROLLED":
        raise_err(ERR_INVALID_STATE, "Enrollment is not ENROLLED")
    program = db.group_programs.get(e.get("program_id"))
    if program is None:
        raise_err(ERR_NOT_FOUND, "Linked GroupProgram does not exist")
    if program.get("status") not in ("OPEN", "RUNNING"):
        raise_err(ERR_INVALID_STATE, "Program is not OPEN or RUNNING")
    e["status"] = "DROPPED"
    # Waitlist promotion.
    domain.promote_waitlist_head(program)
    return success_object(serialize(e))
