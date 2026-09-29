"""Penalties, delinquency points and settlement (PRD §3.8)."""

from flask import Blueprint, g

import clock
import constants
import db
import lookup
import response
import serializers
import validators as V
from errors import (
    ApiError,
    ERR_AUDIT_CASE_NOT_DISCREPANT,
    ERR_PAYMENT_AMOUNT_MISMATCH,
    ERR_PENALTY_ALREADY_SETTLED,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_ENTITY_VERSION,
)
from middleware import (
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_PENALTY_OFFICER,
    ROLE_PROGRAM_ADMIN,
    ROLE_REPORTER_AGENT,
    roles,
)
from services import calculations, cascades

bp = Blueprint("penalties", __name__)

READ_ROLES = (
    ROLE_PENALTY_OFFICER,
    ROLE_PROGRAM_ADMIN,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_REPORTER_AGENT,
)

MATERIAL_FINDINGS = ("MATERIAL_HEAD", "MATERIAL_VALUE", "MATERIAL_BOTH")
DISCREPANT_STATUSES = ("DISCREPANCY", "CLOSED")


def _check_substantiation(violation_type, submission, case):
    if violation_type == "INACCURATE_DATA":
        if (
            case is None
            or case["status"] not in DISCREPANT_STATUSES
            or case["finding"] not in MATERIAL_FINDINGS
        ):
            raise ApiError(
                ERR_AUDIT_CASE_NOT_DISCREPANT,
                "An INACCURATE_DATA assessment requires a discrepant audit case.",
            )
    elif violation_type == "LATE_FILING":
        if submission is None or not submission["is_late"]:
            raise ApiError(
                ERR_AUDIT_CASE_NOT_DISCREPANT,
                "A LATE_FILING assessment requires a filing whose is_late is true.",
            )


@bp.post("/penalty-assessments")
@roles(ROLE_PENALTY_OFFICER)
def create_assessment():
    payload = V.body()
    entity_id = V.get_string(payload, "reporting_entity_id")
    violation_type = V.get_enum(payload, "violation_type", V.VIOLATION_TYPES)
    expected_version = V.get_int(payload, "expected_reporting_entity_version")
    submission_id = V.get_string(payload, "submission_id", required=False)
    case_id = V.get_string(payload, "audit_case_id", required=False)

    entity = lookup.reporting_entity(entity_id)
    submission = lookup.submission(submission_id) if submission_id is not None else None
    case = lookup.audit_case(case_id) if case_id is not None else None

    if case is not None and case["finalized_by_user_id"] is not None:
        if g.user_id == case["finalized_by_user_id"]:
            raise ApiError(
                ERR_SEGREGATION_OF_DUTIES,
                "The assessing user must differ from the user who finalized the audit case.",
            )

    if int(entity["version"]) != int(expected_version):
        raise ApiError(
            ERR_STALE_ENTITY_VERSION,
            "The reporting entity has advanced past the supplied "
            "expected_reporting_entity_version.",
        )

    _check_substantiation(violation_type, submission, case)

    registration = calculations.governing_registration(entity_id)
    breakdown = calculations.compute_penalty(entity, violation_type, submission, registration)

    rec = db.insert(
        db.penalty_assessments,
        {
            "reporting_entity_id": entity_id,
            "audit_case_id": case_id,
            "submission_id": submission_id,
            "violation_type": violation_type,
            "days_late": breakdown["days_late"],
            "base_amount_cents": breakdown["base_amount_cents"],
            "repeat_index": breakdown["repeat_index"],
            "day_tier_multiplier": breakdown["day_tier_multiplier"],
            "repeat_multiplier": breakdown["repeat_multiplier"],
            "volume_factor": breakdown["volume_factor"],
            "suspension_surcharge": breakdown["suspension_surcharge"],
            "assessed_amount_cents": breakdown["assessed_amount_cents"],
            "points": breakdown["points"],
            "delinquency_tier_at_assessment": breakdown["delinquency_tier_at_assessment"],
            "status": "ASSESSED",
            "assessed_by_user_id": g.user_id,
            "waiver_reason": None,
            "settled_at": None,
        },
    )

    cascades.recompute_entity_penalty_ledger(entity)

    tier_after = constants.tier(int(entity["delinquency_points"] or 0))
    if tier_after == "TIER_2" and registration is not None:
        crossed = breakdown["delinquency_tier_at_assessment"] != "TIER_2"
        if registration["status"] == "SUSPENDED":
            registration["status"] = "REVOKED"
            registration["suspended_reason"] = None
            db.touch(registration)
            cascades.void_in_flight_submissions(entity_id)
        elif registration["status"] == "ACTIVE" and crossed:
            registration["status"] = "SUSPENDED"
            registration["suspended_reason"] = "DELINQUENCY_TIER_BREACH"
            db.touch(registration)
            cascades.void_in_flight_submissions(entity_id)

    return response.object_response(serializers.penalty_assessment(rec), 201)


@bp.post("/penalty-assessments/<assessment_id>/pay")
@roles(ROLE_PENALTY_OFFICER)
def pay(assessment_id):
    payload = V.body()
    paid_amount_cents = V.get_int(payload, "paid_amount_cents", minimum=0)

    rec = lookup.penalty_assessment(assessment_id)

    if rec["status"] != "ASSESSED":
        raise ApiError(
            ERR_PENALTY_ALREADY_SETTLED,
            "The assessment has already been settled.",
        )

    if int(paid_amount_cents) != int(rec["assessed_amount_cents"]):
        raise ApiError(
            ERR_PAYMENT_AMOUNT_MISMATCH,
            "Payment must equal the assessed amount exactly.",
        )

    rec["status"] = "PAID"
    rec["settled_at"] = clock.iso_now()
    db.touch(rec)

    entity = db.reporting_entities[rec["reporting_entity_id"]]
    cascades.recompute_entity_penalty_ledger(entity)
    return response.object_response(serializers.penalty_assessment(rec))


@bp.post("/penalty-assessments/<assessment_id>/waive")
@roles(ROLE_PENALTY_OFFICER, ROLE_PROGRAM_ADMIN)
def waive(assessment_id):
    payload = V.body()
    waiver_reason = V.get_string(payload, "waiver_reason", max_len=4000)

    rec = lookup.penalty_assessment(assessment_id)

    if rec["status"] != "ASSESSED":
        raise ApiError(
            ERR_PENALTY_ALREADY_SETTLED,
            "The assessment has already been settled.",
        )

    rec["status"] = "WAIVED"
    rec["waiver_reason"] = waiver_reason
    rec["settled_at"] = clock.iso_now()
    db.touch(rec)

    entity = db.reporting_entities[rec["reporting_entity_id"]]
    cascades.recompute_entity_penalty_ledger(entity)

    registration = calculations.governing_registration(entity["id"])
    if (
        registration is not None
        and registration["status"] == "SUSPENDED"
        and registration["suspended_reason"] == "DELINQUENCY_TIER_BREACH"
        and constants.tier(int(entity["delinquency_points"] or 0)) != "TIER_2"
    ):
        registration["status"] = "ACTIVE"
        registration["suspended_reason"] = None
        db.touch(registration)

    return response.object_response(serializers.penalty_assessment(rec))


@bp.get("/penalty-assessments/<assessment_id>")
@roles(*READ_ROLES)
def get_assessment(assessment_id):
    rec = lookup.penalty_assessment(assessment_id)
    return response.object_response(serializers.penalty_assessment(rec))


@bp.get("/penalty-assessments")
@roles(*READ_ROLES)
def list_assessments():
    limit, offset = V.pagination()
    entity_id = V.query_str("reporting_entity_id")
    case_id = V.query_str("audit_case_id")
    submission_id = V.query_str("submission_id")
    violation_type = V.query_str("violation_type")
    status = V.query_str("status")

    records = db.ordered(db.penalty_assessments.values())
    if entity_id is not None:
        records = [r for r in records if r["reporting_entity_id"] == entity_id]
    if case_id is not None:
        records = [r for r in records if r["audit_case_id"] == case_id]
    if submission_id is not None:
        records = [r for r in records if r["submission_id"] == submission_id]
    if violation_type is not None:
        records = [r for r in records if r["violation_type"] == violation_type]
    if status is not None:
        records = [r for r in records if r["status"] == status]

    page, total = V.paginate(records, limit, offset)
    return response.array_response(
        [serializers.penalty_assessment(r) for r in page], limit, offset, total
    )
