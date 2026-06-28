"""AssessmentRecord endpoints (PRD §3.11)."""
from flask import Blueprint

import errors
from db import db, new_common_fields, parse_iso
from middleware import get_auth, require_role
from response import object_response, array_response
from services.common import (
    get_json_body, require_fields, require_enum, parse_pagination,
    sort_created_asc, paginate, serialize, serialize_list, str_arg, optional_enum,
)

bp = Blueprint("assessment_records", __name__)

WORK_AREAS = {"PRACTICAL_LIFE", "SENSORIAL", "LANGUAGE", "MATHEMATICS", "CULTURAL"}
MASTERY_LEVELS = {"INTRODUCED", "PRACTICING", "MASTERED"}
READ_ROLES = {"Registrar", "Guide", "Parent"}


@bp.route("/assessment-records", methods=["POST"])
def create_assessment_record():
    _, role = get_auth()
    require_role(role, {"Guide"})
    body = get_json_body()
    require_fields(body, ["student_id", "enrollment_id", "work_area", "mastery_level", "work_cycle_date"])

    student_id = body["student_id"]
    enrollment_id = body["enrollment_id"]
    for val, label in ((student_id, "student_id"), (enrollment_id, "enrollment_id")):
        if not isinstance(val, str):
            raise errors.invalid_request(f"{label} must be a string.")
    work_area = require_enum(body, "work_area", WORK_AREAS)
    mastery_level = require_enum(body, "mastery_level", MASTERY_LEVELS)
    work_cycle_date = body["work_cycle_date"]
    if not isinstance(work_cycle_date, str):
        raise errors.invalid_request("work_cycle_date must be an ISO 8601 string.")
    try:
        parse_iso(work_cycle_date)
    except (ValueError, TypeError):
        raise errors.invalid_request("work_cycle_date must be a valid ISO 8601 instant.")

    portfolio_included = True
    if "portfolio_included" in body and body["portfolio_included"] is not None:
        if not isinstance(body["portfolio_included"], bool):
            raise errors.invalid_request("portfolio_included must be a boolean.")
        portfolio_included = body["portfolio_included"]

    # Body FK existence (PRD §2.9).
    if student_id not in db.students:
        raise errors.not_found("student_id does not exist.")
    if enrollment_id not in db.enrollments:
        raise errors.not_found("enrollment_id does not exist.")

    rec = new_common_fields()
    rec.update({
        "student_id": student_id,
        "enrollment_id": enrollment_id,
        "work_area": work_area,
        "mastery_level": mastery_level,
        "work_cycle_date": work_cycle_date,
        "portfolio_included": portfolio_included,
    })
    db.assessment_records[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/assessment-records/<rec_id>", methods=["GET"])
def get_assessment_record(rec_id):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    rec = db.assessment_records.get(rec_id)
    if rec is None:
        raise errors.not_found("Assessment record not found.")
    return object_response(serialize(rec), 200)


@bp.route("/assessment-records", methods=["GET"])
def list_assessment_records():
    _, role = get_auth()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    student_id = str_arg("student_id")
    enrollment_id = str_arg("enrollment_id")
    work_area = optional_enum(str_arg("work_area"), WORK_AREAS, "work_area")

    records = list(db.assessment_records.values())
    if student_id is not None:
        records = [r for r in records if r["student_id"] == student_id]
    if enrollment_id is not None:
        records = [r for r in records if r["enrollment_id"] == enrollment_id]
    if work_area is not None:
        records = [r for r in records if r["work_area"] == work_area]
    records = sort_created_asc(records)
    page, total = paginate(records, limit, offset)
    return array_response(serialize_list(page), limit, offset, total)
