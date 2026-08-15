"""Student endpoints."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_DUPLICATE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_UNAUTHORIZED,
    ERR_CONFIDENTIALITY_VIOLATION,
)
from middleware import require_roles
from response import success_object, success_list
from services import domain
from services.serializers import serialize_student_for_role, serialize_students_for_role
from util import (
    apply_filters,
    get_json_body,
    optional_field,
    paginate,
    parse_pagination,
    require_enum,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("students", __name__)

ENROLLMENT_STATUSES = {"ENROLLED", "LEAVE_OF_ABSENCE", "WITHDRAWN", "GRADUATED"}
FUNDING_MODELS = {"STUDENT_FEE", "INSURANCE", "SPLIT"}


@bp.route("/ucc/students", methods=["POST"])
@require_roles("FrontDesk", "Registrar")
def create_student(_user_id: str, _role: str):
    body = get_json_body()
    student_number = require_string(body, "student_number")
    full_name = require_string(body, "full_name")
    enrollment_status = require_enum(body, "enrollment_status", ENROLLMENT_STATUSES)
    funding_model = require_enum(body, "funding_model", FUNDING_MODELS)
    academic_record_flags = optional_field(body, "academic_record_flags", [])
    if not isinstance(academic_record_flags, list):
        raise_err(ERR_INVALID_REQUEST, "academic_record_flags must be an array")

    # Uniqueness
    for s in db.students.values():
        if s.get("student_number") == student_number:
            raise_err(ERR_DUPLICATE, "student_number already exists")

    student = {
        "student_number": student_number,
        "full_name": full_name,
        "enrollment_status": enrollment_status,
        "funding_model": funding_model,
        "academic_record_flags": academic_record_flags,
        "no_show_strike_count": 0,
        "strike_reset_anchor": "1970-01-01T00:00:00Z",
        "booking_posture": "CLEAR",
    }
    db.stamp_new(student)
    db.students[student["id"]] = student
    return success_object(serialize_student_for_role(student, _role), 201)


@bp.route("/ucc/students/<student_id>", methods=["GET"])
@require_roles("FrontDesk", "Registrar", "Counselor", "TriageScreener", "ClinicalDirector", "ReferralCoordinator")
def get_student(student_id: str, _user_id: str, _role: str):
    student = db.students.get(student_id)
    if student is None:
        raise_err(ERR_NOT_FOUND, "Student id does not exist")
    return success_object(serialize_student_for_role(student, _role))


@bp.route("/ucc/students", methods=["GET"])
@require_roles("FrontDesk", "Registrar", "Counselor", "TriageScreener", "ClinicalDirector")
def list_students(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.students.values()))
    items = apply_filters(items, ["enrollment_status", "booking_posture"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_students_for_role(page, _role), limit, offset, total)


@bp.route("/ucc/students/<student_id>", methods=["PATCH"])
@require_roles("FrontDesk", "Registrar")
def patch_student(student_id: str, _user_id: str, _role: str):
    student = db.students.get(student_id)
    if student is None:
        raise_err(ERR_NOT_FOUND, "Student id does not exist")
    body = get_json_body()

    # Field-level write permissions per PRD §3.1.
    # Registrar: enrollment_status, academic_record_flags
    # FrontDesk: funding_model
    # Clinical computed fields never writable.

    if "enrollment_status" in body:
        if _role != "Registrar":
            raise_err(ERR_UNAUTHORIZED, "Only Registrar may write enrollment_status")
        v = body["enrollment_status"]
        if not isinstance(v, str) or v not in ENROLLMENT_STATUSES:
            raise_err(ERR_INVALID_REQUEST, "enrollment_status out of range")
        student["enrollment_status"] = v

    if "academic_record_flags" in body:
        if _role != "Registrar":
            raise_err(ERR_UNAUTHORIZED, "Only Registrar may write academic_record_flags")
        v = body["academic_record_flags"]
        if not isinstance(v, list):
            raise_err(ERR_INVALID_REQUEST, "academic_record_flags must be an array")
        student["academic_record_flags"] = v

    if "funding_model" in body:
        if _role != "FrontDesk":
            raise_err(ERR_UNAUTHORIZED, "Only FrontDesk may write funding_model")
        v = body["funding_model"]
        if not isinstance(v, str) or v not in FUNDING_MODELS:
            raise_err(ERR_INVALID_REQUEST, "funding_model out of range")
        student["funding_model"] = v

    db.touch(student)
    return success_object(serialize_student_for_role(student, _role))


@bp.route("/ucc/students/<student_id>/strikes/reset", methods=["POST"])
@require_roles("ClinicalDirector")
def reset_strikes(student_id: str, _user_id: str, _role: str):
    student = db.students.get(student_id)
    if student is None:
        raise_err(ERR_NOT_FOUND, "Student id does not exist")
    # Precondition: posture SUSPENDED
    if student.get("booking_posture") != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "Student booking_posture is not SUSPENDED")
    student["strike_reset_anchor"] = db.now_logical_iso()
    # Recompute strikes (will be 0 since anchor == now)
    domain.recompute_student_strikes(student)
    student["booking_posture"] = "CLEAR"
    db.touch(student)
    return success_object(serialize_student_for_role(student, _role))
