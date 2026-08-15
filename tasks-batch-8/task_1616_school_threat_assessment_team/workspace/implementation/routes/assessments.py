"""Risk assessment endpoints: drafting, scoring, adjudication (PRD section 3.4)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_ASSESSMENT_NOT_DRAFT,
    ERR_ASSESSMENT_NOT_SUBMITTED,
    ERR_CASE_NOT_ASSESSABLE,
    ERR_NOT_FOUND,
    ERR_OPEN_ASSESSMENT_EXISTS,
    ERR_SOD_SELF_APPROVAL,
)
from middleware import require_roles
from response import success_object
from services import domain
from util import (
    get_json_body,
    require_enum,
    require_string,
    require_string_allow_empty,
)

bp = Blueprint("assessments", __name__)

VARIANTS = {"STANDARD", "EXPEDITED"}


def _get_assessment_or_404(assessment_id: str) -> dict:
    assessment = db.risk_assessments.get(assessment_id)
    if assessment is None:
        raise_err(ERR_NOT_FOUND, "Risk assessment id does not exist")
    return assessment


@bp.route("/risk-assessments", methods=["POST"])
@require_roles("ThreatAssessor")
def create_assessment(_user_id: str, _role: str):
    body = get_json_body()
    case_id = require_string(body, "case_id")
    variant = require_enum(body, "variant", VARIANTS)
    factors = domain.validate_factors(body.get("factors"))

    case = domain.get_case_or_404(case_id)
    if case["status"] not in ("UNDER_ASSESSMENT", "PLAN_ACTIVE"):
        raise_err(ERR_CASE_NOT_ASSESSABLE,
                  "Risk assessment creation requires status UNDER_ASSESSMENT or PLAN_ACTIVE")
    if domain.has_open_assessment(case["id"]):
        raise_err(ERR_OPEN_ASSESSMENT_EXISTS,
                  "Case already has a DRAFT or SUBMITTED assessment")

    raw_score, risk_level = domain.compute_assessment_score(variant, factors)
    assessment = {
        "case_id": case["id"],
        "variant": variant,
        "factors": factors,
        "raw_score": raw_score,
        "risk_level": risk_level,
        "status": "DRAFT",
        "created_by_user_id": _user_id,
        "finalized_at": None,
        "superseded_at": None,
    }
    db.stamp_new(assessment)
    db.risk_assessments[assessment["id"]] = assessment
    return success_object(db.public(assessment), 201)


@bp.route("/risk-assessments/<assessment_id>", methods=["PUT"])
@require_roles("ThreatAssessor")
def update_assessment(assessment_id: str, _user_id: str, _role: str):
    body = get_json_body()
    variant = None
    if "variant" in body and body["variant"] is not None:
        variant = require_enum(body, "variant", VARIANTS)
    factors = None
    if "factors" in body and body["factors"] is not None:
        factors = domain.validate_factors(body["factors"])

    assessment = _get_assessment_or_404(assessment_id)
    if assessment["status"] != "DRAFT":
        raise_err(ERR_ASSESSMENT_NOT_DRAFT, "PUT requires assessment status DRAFT")

    if variant is not None:
        assessment["variant"] = variant
    if factors is not None:
        assessment["factors"] = factors
    raw_score, risk_level = domain.compute_assessment_score(
        assessment["variant"], assessment["factors"]
    )
    assessment["raw_score"] = raw_score
    assessment["risk_level"] = risk_level
    db.touch(assessment)
    return success_object(db.public(assessment))


@bp.route("/risk-assessments/<assessment_id>/submit", methods=["POST"])
@require_roles("ThreatAssessor")
def submit_assessment(assessment_id: str, _user_id: str, _role: str):
    assessment = _get_assessment_or_404(assessment_id)
    if assessment["status"] != "DRAFT":
        raise_err(ERR_ASSESSMENT_NOT_DRAFT, "Submit requires assessment status DRAFT")
    assessment["status"] = "SUBMITTED"
    db.touch(assessment)
    return success_object(db.public(assessment))


@bp.route("/risk-assessments/<assessment_id>/return", methods=["POST"])
@require_roles("TeamLead")
def return_assessment(assessment_id: str, _user_id: str, _role: str):
    body = get_json_body()
    return_reason = require_string_allow_empty(body, "return_reason")

    assessment = _get_assessment_or_404(assessment_id)
    if assessment["status"] != "SUBMITTED":
        raise_err(ERR_ASSESSMENT_NOT_SUBMITTED,
                  "Return requires assessment status SUBMITTED")

    assessment["status"] = "DRAFT"
    db.touch(assessment)
    domain.audit(
        assessment["case_id"],
        "ASSESSMENT_RETURNED",
        f"Assessment {assessment_id} returned to DRAFT: {return_reason}",
        _user_id,
        _role,
    )
    return success_object(db.public(assessment))


@bp.route("/risk-assessments/<assessment_id>/finalize", methods=["POST"])
@require_roles("TeamLead")
def finalize_assessment(assessment_id: str, _user_id: str, _role: str):
    assessment = _get_assessment_or_404(assessment_id)
    if assessment["status"] != "SUBMITTED":
        raise_err(ERR_ASSESSMENT_NOT_SUBMITTED,
                  "Finalize requires assessment status SUBMITTED")
    # Segregation of duties: the finalizer may not be the drafting assessor.
    if _user_id == assessment["created_by_user_id"]:
        raise_err(ERR_SOD_SELF_APPROVAL,
                  "Finalizer X-User-ID must differ from the assessment creator")

    assessment["status"] = "FINALIZED"
    assessment["finalized_at"] = db.now_logical_iso()
    db.touch(assessment)

    case = domain.get_case_or_404(assessment["case_id"])
    case["risk_level"] = assessment["risk_level"]

    domain.audit(
        case["id"],
        "ASSESSMENT_FINALIZED",
        f"Risk assessment {assessment_id} finalized: raw_score {assessment['raw_score']}, "
        f"risk_level {assessment['risk_level']}",
        _user_id,
        _role,
    )

    # Any other FINALIZED assessment for the same case -> SUPERSEDED.
    for other in domain.case_children(db.risk_assessments, case["id"]):
        if other["id"] != assessment["id"] and other["status"] == "FINALIZED":
            other["status"] = "SUPERSEDED"
            other["superseded_at"] = db.now_logical_iso()
            db.touch(other)

    # IMMINENT cascade: auto LE referral -> case escalation -> plan needs_review.
    if assessment["risk_level"] == "IMMINENT" and not domain.has_live_le_referral(case["id"]):
        referral = domain.auto_create_le_referral(
            case, _user_id, _role, "IMMINENT assessment finalized"
        )
        case["escalation_flag"] = True
        domain.audit(
            case["id"],
            "ESCALATION_RAISED",
            f"Escalation raised by auto-created referral {referral['id']} "
            "on IMMINENT finalization",
            _user_id,
            _role,
        )
        plan = domain.active_plan_for_case(case["id"])
        if plan is not None:
            plan["needs_review"] = True
            db.touch(plan)

    db.touch(case)  # exactly one case-version increment for the finalization
    return success_object(db.public(assessment))
