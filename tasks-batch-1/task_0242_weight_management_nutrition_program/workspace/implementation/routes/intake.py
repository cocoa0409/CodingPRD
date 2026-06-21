"""IntakeAssessment endpoints + lifecycle (PRD 3.3)."""
from flask import Blueprint, request

from common import (as_int, as_number, as_str, get_body, init_common,
                    parse_pagination, require, sort_by_creation, touch)
from db import db
from errors import (ERR_INVALID_REQUEST, ERR_INVALID_STATE, raise_error)
from lookups import get_intake, get_member, get_program
from middleware import require_roles
from response import paginated, success
from serializers import serialize, serialize_list
import calculations as calc

bp = Blueprint("intake", __name__)


def _recompute(assessment, member):
    bmi = calc.compute_bmi(assessment["weight_kg"], member["height_cm"])
    assessment["bmi"] = bmi
    assessment["risk_band"] = calc.compute_risk_band(bmi, assessment["comorbidity_count"])


@bp.route("/wm/intake-assessments", methods=["POST"])
@require_roles("ProgramAdmin", "Member")
def create_intake():
    body = get_body()
    member_id = as_str(require(body, "member_id"), "member_id")
    member = get_member(member_id)  # ERR_MEMBER_NOT_FOUND

    weight_kg = as_number(require(body, "weight_kg"), "weight_kg")
    if weight_kg <= 0:
        raise_error(ERR_INVALID_REQUEST, "weight_kg must be > 0")

    comorbidity_count = 0
    if body.get("comorbidity_count") is not None:
        comorbidity_count = as_int(body["comorbidity_count"], "comorbidity_count")
        if comorbidity_count < 0:
            raise_error(ERR_INVALID_REQUEST, "comorbidity_count must be >= 0")

    review_notes = None
    if body.get("review_notes") is not None:
        review_notes = as_str(body["review_notes"], "review_notes", allow_empty=True)

    assessment = {
        "member_id": member_id,
        "program_id": member["program_id"],
        "weight_kg": weight_kg,
        "bmi": None,
        "comorbidity_count": comorbidity_count,
        "risk_band": None,
        "review_notes": review_notes,
        "revision_round": 0,
        "status": "DRAFT",
    }
    init_common(assessment)
    db.intake_assessments[assessment["id"]] = assessment

    # registering the assessment moves the member to INTAKE_PENDING
    member["status"] = "INTAKE_PENDING"
    touch(member)

    return success(serialize(assessment), 201)


@bp.route("/wm/intake-assessments", methods=["GET"])
@require_roles("ProgramAdmin", "Clinician", "Member")
def list_intake():
    limit, offset = parse_pagination()
    items = list(db.intake_assessments.values())
    member_id = request.args.get("member_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if member_id is not None:
        items = [a for a in items if a["member_id"] == member_id]
    if program_id is not None:
        items = [a for a in items if a["program_id"] == program_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sort_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return paginated(serialize_list(page), limit, offset, total)


@bp.route("/wm/intake-assessments/<assessment_id>", methods=["GET"])
@require_roles("ProgramAdmin", "Clinician", "Member")
def get_one_intake(assessment_id):
    return success(serialize(get_intake(assessment_id)), 200)


@bp.route("/wm/intake-assessments/<assessment_id>/submit", methods=["POST"])
@require_roles("ProgramAdmin", "Member")
def submit_intake(assessment_id):
    assessment = get_intake(assessment_id)
    body = get_body()

    if assessment["status"] not in ("DRAFT", "NEEDS_REVISION"):
        raise_error(ERR_INVALID_STATE, "Submit allowed only from DRAFT or NEEDS_REVISION")

    # optional updates to weight/comorbidity
    if body.get("weight_kg") is not None:
        new_weight = as_number(body["weight_kg"], "weight_kg")
        assessment["weight_kg"] = new_weight
    if body.get("comorbidity_count") is not None:
        cc = as_int(body["comorbidity_count"], "comorbidity_count")
        if cc < 0:
            raise_error(ERR_INVALID_REQUEST, "comorbidity_count must be >= 0")
        assessment["comorbidity_count"] = cc

    if assessment["weight_kg"] <= 0:
        raise_error(ERR_INVALID_REQUEST, "weight_kg must be > 0")

    was_revision = assessment["status"] == "NEEDS_REVISION"
    assessment["status"] = "SUBMITTED"
    if was_revision:
        assessment["revision_round"] += 1

    member = get_member(assessment["member_id"])
    _recompute(assessment, member)
    touch(assessment)
    return success(serialize(assessment), 200)


@bp.route("/wm/intake-assessments/<assessment_id>/start-review", methods=["POST"])
@require_roles("Clinician")
def start_review(assessment_id):
    assessment = get_intake(assessment_id)
    if assessment["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "start-review allowed only from SUBMITTED")
    assessment["status"] = "UNDER_REVIEW"
    touch(assessment)
    return success(serialize(assessment), 200)


@bp.route("/wm/intake-assessments/<assessment_id>/request-revision", methods=["POST"])
@require_roles("Clinician")
def request_revision(assessment_id):
    assessment = get_intake(assessment_id)
    body = get_body()
    if assessment["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "request-revision allowed only from UNDER_REVIEW")
    notes = body.get("review_notes")
    if not isinstance(notes, str) or notes.strip() == "":
        raise_error(ERR_INVALID_REQUEST, "review_notes must be non-empty")
    assessment["review_notes"] = notes
    assessment["status"] = "NEEDS_REVISION"
    touch(assessment)
    return success(serialize(assessment), 200)


@bp.route("/wm/intake-assessments/<assessment_id>/approve", methods=["POST"])
@require_roles("Clinician")
def approve_intake(assessment_id):
    assessment = get_intake(assessment_id)
    if assessment["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "approve allowed only from UNDER_REVIEW")
    assessment["status"] = "APPROVED"
    touch(assessment)
    member = get_member(assessment["member_id"])
    member["baseline_weight_kg"] = assessment["weight_kg"]
    touch(member)
    return success(serialize(assessment), 200)


@bp.route("/wm/intake-assessments/<assessment_id>/reject", methods=["POST"])
@require_roles("Clinician")
def reject_intake(assessment_id):
    assessment = get_intake(assessment_id)
    body = get_body()
    if assessment["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "reject allowed only from UNDER_REVIEW")
    notes = body.get("review_notes")
    if not isinstance(notes, str) or notes.strip() == "":
        raise_error(ERR_INVALID_REQUEST, "review_notes must be non-empty")
    assessment["review_notes"] = notes
    assessment["status"] = "REJECTED"
    touch(assessment)
    return success(serialize(assessment), 200)
