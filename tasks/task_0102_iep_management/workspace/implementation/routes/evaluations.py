"""Eligibility evaluations and their state machine."""

from flask import Blueprint, request

from core.auth import require_role
from core.envelope import success_object, success_array
from core.errors import APIError
from core.pagination import parse_pagination, paginate
from core.store import (
    EVALUATIONS, CONSENTS, STUDENTS, IEPS, stamp_create, stamp_update,
    stamp_create_event,
)
from core.validation import (
    get_district, get_student, get_evaluation, require_json_body, check_version,
)
from services.cascades import cascade_iep_revoke
from services.computations import (
    compute_triennial_due_date,
    compute_triennial_status,
)
from services.serializers import evaluation_dto


bp = Blueprint("evaluations", __name__)


ALLOWED_EVAL_TYPES = {"INITIAL", "TRIENNIAL", "INTERIM"}
ALLOWED_DISABILITY_CATEGORIES = {
    "SLD", "OHI", "ASD", "SI", "OI", "ED", "ID",
    "HI", "VI", "DB", "TBI", "MD", "DD",
}


@bp.route("/districts/<district_id>/students/<student_id>/eligibility-evaluations", methods=["POST"])
def create_evaluation(district_id, student_id):
    user_id, _ = require_role(["SchoolPsychologist"])
    district = get_district(district_id)
    get_student(district_id, student_id)

    body = require_json_body()
    eval_type = body.get("evaluation_type")
    if eval_type not in ALLOWED_EVAL_TYPES:
        raise APIError("ERR_INVALID_REQUEST", "evaluation_type must be INITIAL, TRIENNIAL, or INTERIM.")

    evaluation = {
        "student_id": student_id,
        "district_id": district_id,
        "evaluation_type": eval_type,
        "is_reevaluation": eval_type == "TRIENNIAL",
        "disability_categories": [],
        "evaluator_user_id": user_id,
        "requested_at": district["current_date"],
        "consent_received_at": None,
        "finalized_at": None,
        "status": "REQUESTED",
    }
    stamp_create(evaluation)
    EVALUATIONS[evaluation["id"]] = evaluation
    return success_object(evaluation_dto(evaluation), http_status=201)


@bp.route(
    "/districts/<district_id>/students/<student_id>/eligibility-evaluations/<evaluation_id>/request-consent",
    methods=["POST"]
)
def request_consent(district_id, student_id, evaluation_id):
    require_role(["SchoolPsychologist"])
    district = get_district(district_id)
    get_student(district_id, student_id)
    evaluation = get_evaluation(district_id, student_id, evaluation_id)
    body = require_json_body()
    check_version(body.get("version"), evaluation.get("version", 1))

    if evaluation.get("status") != "REQUESTED":
        raise APIError("ERR_EVALUATION_NOT_REQUESTED", "Evaluation is not in REQUESTED.")

    # Create the gating PENDING ParentalConsent.
    consent = {
        "student_id": student_id,
        "district_id": district_id,
        "scope": "EVALUATION",
        "target_resource_type": "EligibilityEvaluation",
        "target_resource_id": evaluation_id,
        "requested_at": district["current_date"],
        "decided_at": None,
        "withdrawn_at": None,
        "parent_user_id": None,
        "status": "PENDING",
    }
    stamp_create_event(consent)
    CONSENTS[consent["id"]] = consent

    evaluation["status"] = "CONSENT_PENDING"
    stamp_update(evaluation)
    return success_object(evaluation_dto(evaluation))


@bp.route(
    "/districts/<district_id>/students/<student_id>/eligibility-evaluations/<evaluation_id>/finalize",
    methods=["POST"]
)
def finalize_evaluation(district_id, student_id, evaluation_id):
    user_id, _ = require_role(["SchoolPsychologist"])
    district = get_district(district_id)
    student = get_student(district_id, student_id)
    evaluation = get_evaluation(district_id, student_id, evaluation_id)
    body = require_json_body()
    check_version(body.get("version"), evaluation.get("version", 1))

    if evaluation.get("status") != "IN_PROGRESS":
        raise APIError("ERR_EVALUATION_NOT_IN_PROGRESS", "Evaluation is not in IN_PROGRESS.")

    # Segregation of duties: psychologist cannot also be the student's parent.
    if student.get("parent_user_id") == user_id:
        raise APIError(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            "Acting psychologist may not also be the student's parent.",
        )

    disability_categories = body.get("disability_categories")
    if not isinstance(disability_categories, list):
        raise APIError("ERR_INVALID_REQUEST", "disability_categories must be an array.")
    for cat in disability_categories:
        if cat not in ALLOWED_DISABILITY_CATEGORIES:
            raise APIError("ERR_INVALID_REQUEST", f"Invalid disability_category: {cat}")

    evaluation["disability_categories"] = list(disability_categories)
    evaluation["finalized_at"] = district["current_date"]
    if disability_categories:
        evaluation["status"] = "ELIGIBLE"
        student["triennial_reevaluation_due_date"] = compute_triennial_due_date(
            evaluation["finalized_at"]
        )
        student["current_eligibility_evaluation_id"] = evaluation_id
        student["triennial_status"] = compute_triennial_status(student, district["current_date"])
    else:
        evaluation["status"] = "INELIGIBLE"
        student["current_eligibility_evaluation_id"] = evaluation_id
        # Cascade if student currently has an IEP.
        if student.get("current_iep_id"):
            iep = IEPS.get(student["current_iep_id"])
            if iep is not None and iep.get("status") in ("ACTIVE", "AMENDMENT_PENDING"):
                cascade_iep_revoke(iep, district["current_date"])
        student["triennial_status"] = compute_triennial_status(student, district["current_date"])

    stamp_update(evaluation)
    stamp_update(student)
    return success_object(evaluation_dto(evaluation))


@bp.route("/districts/<district_id>/students/<student_id>/eligibility-evaluations", methods=["GET"])
def list_evaluations(district_id, student_id):
    user_id, role = require_role(["DistrictAdmin", "SchoolPsychologist", "SpecialEducationTeacher", "Parent"])
    get_district(district_id)
    student = get_student(district_id, student_id)
    if role == "Parent" and user_id != student.get("parent_user_id"):
        raise APIError("ERR_PARENT_OWNERSHIP_MISMATCH", "Parent may only act on their own student.")
    limit, offset = parse_pagination()
    status_q = request.args.get("status")
    rows = [e for e in EVALUATIONS.values() if e.get("student_id") == student_id]
    if status_q:
        rows = [e for e in rows if e.get("status") == status_q]
    rows.sort(key=lambda r: r.get("created_at", ""))
    page, total = paginate([evaluation_dto(e) for e in rows], limit, offset)
    return success_array(page, limit=limit, offset=offset, total_count=total)


@bp.route("/districts/<district_id>/students/<student_id>/eligibility-evaluations/<evaluation_id>", methods=["GET"])
def get_evaluation_route(district_id, student_id, evaluation_id):
    user_id, role = require_role(["DistrictAdmin", "SchoolPsychologist", "SpecialEducationTeacher", "Parent"])
    student = get_student(district_id, student_id)
    if role == "Parent" and user_id != student.get("parent_user_id"):
        raise APIError("ERR_PARENT_OWNERSHIP_MISMATCH", "Parent may only act on their own student.")
    evaluation = get_evaluation(district_id, student_id, evaluation_id)
    return success_object(evaluation_dto(evaluation))
