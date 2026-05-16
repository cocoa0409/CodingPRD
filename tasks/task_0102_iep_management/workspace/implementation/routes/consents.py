"""Parental consent CRUD + state machine (approve / reject / withdraw)."""

from flask import Blueprint, request

from core.auth import require_role
from core.envelope import success_object, success_array
from core.errors import APIError
from core.pagination import parse_pagination, paginate
from core.store import (
    CONSENTS, EVALUATIONS, IEPS, SERVICES, STUDENTS, stamp_update,
    stamp_create_event,
)
from core.validation import (
    get_district, get_student, get_consent, require_json_body, check_version,
    get_iep, get_service,
)
from services.cascades import (
    cascade_iep_revoke,
    cascade_consent_withdraw_related_service,
)
from services.serializers import consent_dto


bp = Blueprint("consents", __name__)


ALLOWED_SCOPE_TARGET_PAIRS = {
    ("IEP_IMPLEMENTATION", "IEP"),
    ("RELATED_SERVICE", "RelatedService"),
    ("PLACEMENT_CHANGE", "Student"),
    ("EVALUATION", "EligibilityEvaluation"),
}


def _check_parent_ownership(student, user_id):
    if user_id != student.get("parent_user_id"):
        raise APIError("ERR_PARENT_OWNERSHIP_MISMATCH", "Parent may only act on their own student.")


@bp.route("/districts/<district_id>/students/<student_id>/parental-consents", methods=["POST"])
def create_consent(district_id, student_id):
    user_id, role = require_role(["SpecialEducationTeacher", "RelatedServiceProvider"])
    district = get_district(district_id)
    student = get_student(district_id, student_id)
    body = require_json_body()

    scope = body.get("scope")
    target_resource_type = body.get("target_resource_type")
    target_resource_id = body.get("target_resource_id")

    if scope not in {"IEP_IMPLEMENTATION", "RELATED_SERVICE", "PLACEMENT_CHANGE"}:
        # EVALUATION-scope consents are auto-created via request-consent endpoint only.
        raise APIError(
            "ERR_INVALID_REQUEST",
            "scope must be IEP_IMPLEMENTATION, RELATED_SERVICE, or PLACEMENT_CHANGE.",
        )
    if (scope, target_resource_type) not in ALLOWED_SCOPE_TARGET_PAIRS:
        raise APIError("ERR_INVALID_REQUEST", "scope and target_resource_type do not match.")
    if not isinstance(target_resource_id, str) or not target_resource_id:
        raise APIError("ERR_INVALID_REQUEST", "target_resource_id is required.")

    # Cross-aggregate referential integrity: target must belong to same student/district.
    if scope == "IEP_IMPLEMENTATION":
        iep = IEPS.get(target_resource_id)
        if iep is None:
            raise APIError("ERR_IEP_NOT_FOUND", "Target IEP not found.")
        if iep.get("student_id") != student_id or iep.get("district_id") != district_id:
            raise APIError("ERR_CROSS_STUDENT_REFERENCE", "IEP belongs to a different student/district.")
    elif scope == "RELATED_SERVICE":
        svc = SERVICES.get(target_resource_id)
        if svc is None:
            raise APIError("ERR_SERVICE_NOT_FOUND", "Target service not found.")
        if svc.get("student_id") != student_id or svc.get("district_id") != district_id:
            raise APIError("ERR_CROSS_STUDENT_REFERENCE", "Service belongs to a different student/district.")
    elif scope == "PLACEMENT_CHANGE":
        if target_resource_id != student_id:
            raise APIError("ERR_CROSS_STUDENT_REFERENCE", "target_resource_id must equal the student id.")

    consent = {
        "student_id": student_id,
        "district_id": district_id,
        "scope": scope,
        "target_resource_type": target_resource_type,
        "target_resource_id": target_resource_id,
        "requested_at": district["current_date"],
        "decided_at": None,
        "withdrawn_at": None,
        "parent_user_id": None,
        "status": "PENDING",
    }
    stamp_create_event(consent)
    CONSENTS[consent["id"]] = consent
    return success_object(consent_dto(consent), http_status=201)


@bp.route("/districts/<district_id>/students/<student_id>/parental-consents/<consent_id>/approve", methods=["POST"])
def approve_consent(district_id, student_id, consent_id):
    user_id, _ = require_role(["Parent"])
    district = get_district(district_id)
    student = get_student(district_id, student_id)
    _check_parent_ownership(student, user_id)
    consent = get_consent(district_id, student_id, consent_id)

    if consent.get("status") != "PENDING":
        raise APIError("ERR_CONSENT_NOT_PENDING", "Consent is not in PENDING.")

    consent["status"] = "APPROVED"
    consent["decided_at"] = district["current_date"]
    consent["parent_user_id"] = user_id

    # Side effects per scope.
    scope = consent.get("scope")
    if scope == "EVALUATION":
        ev = EVALUATIONS.get(consent.get("target_resource_id"))
        if ev is not None and ev.get("status") == "CONSENT_PENDING":
            ev["status"] = "IN_PROGRESS"
            ev["consent_received_at"] = consent["decided_at"]
            stamp_update(ev)
    elif scope == "RELATED_SERVICE":
        svc = SERVICES.get(consent.get("target_resource_id"))
        if svc is not None:
            svc["consent_id"] = consent_id
            stamp_update(svc)
    return success_object(consent_dto(consent))


@bp.route("/districts/<district_id>/students/<student_id>/parental-consents/<consent_id>/reject", methods=["POST"])
def reject_consent(district_id, student_id, consent_id):
    user_id, _ = require_role(["Parent"])
    district = get_district(district_id)
    student = get_student(district_id, student_id)
    _check_parent_ownership(student, user_id)
    consent = get_consent(district_id, student_id, consent_id)
    if consent.get("status") != "PENDING":
        raise APIError("ERR_CONSENT_NOT_PENDING", "Consent is not in PENDING.")
    consent["status"] = "REJECTED"
    consent["decided_at"] = district["current_date"]
    consent["parent_user_id"] = user_id
    return success_object(consent_dto(consent))


@bp.route("/districts/<district_id>/students/<student_id>/parental-consents/<consent_id>/withdraw", methods=["POST"])
def withdraw_consent(district_id, student_id, consent_id):
    user_id, _ = require_role(["Parent"])
    district = get_district(district_id)
    student = get_student(district_id, student_id)
    _check_parent_ownership(student, user_id)
    consent = get_consent(district_id, student_id, consent_id)
    if consent.get("status") != "APPROVED":
        raise APIError("ERR_CONSENT_NOT_APPROVED", "Consent is not in APPROVED.")
    consent["status"] = "WITHDRAWN"
    consent["withdrawn_at"] = district["current_date"]

    scope = consent.get("scope")
    if scope == "RELATED_SERVICE":
        cascade_consent_withdraw_related_service(consent, district["current_date"])
    elif scope == "IEP_IMPLEMENTATION":
        iep = IEPS.get(consent.get("target_resource_id"))
        if iep is not None and iep.get("status") in ("ACTIVE", "AMENDMENT_PENDING"):
            cascade_iep_revoke(iep, district["current_date"])
    elif scope == "EVALUATION":
        # Evaluation remains; psychologist must request a new consent row.
        pass
    return success_object(consent_dto(consent))


@bp.route("/districts/<district_id>/students/<student_id>/parental-consents", methods=["GET"])
def list_consents(district_id, student_id):
    user_id, role = require_role(["DistrictAdmin", "SpecialEducationTeacher",
                                  "RelatedServiceProvider", "SchoolPsychologist", "Parent"])
    student = get_student(district_id, student_id)
    if role == "Parent" and user_id != student.get("parent_user_id"):
        raise APIError("ERR_PARENT_OWNERSHIP_MISMATCH", "Parent may only act on their own student.")
    limit, offset = parse_pagination()
    scope_q = request.args.get("scope")
    status_q = request.args.get("status")
    rows = [c for c in CONSENTS.values() if c.get("student_id") == student_id]
    if scope_q:
        rows = [c for c in rows if c.get("scope") == scope_q]
    if status_q:
        rows = [c for c in rows if c.get("status") == status_q]
    rows.sort(key=lambda c: c.get("created_at", ""))
    page, total = paginate([consent_dto(c) for c in rows], limit, offset)
    return success_array(page, limit=limit, offset=offset, total_count=total)
