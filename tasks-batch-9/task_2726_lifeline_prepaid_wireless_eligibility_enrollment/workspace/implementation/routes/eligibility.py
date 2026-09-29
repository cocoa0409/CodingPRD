"""National Verifier determinations and documentation resubmission."""
from flask import Blueprint

import db
import response
import validation as v
from errors import ApiError
from routes.common import (MATCHED_BENEFITS, NATIONAL_VERIFIER, PROVIDER_AGENT,
                           ROLES_ALL, authenticate, get_check)
from services import calc, derive

bp = Blueprint("eligibility", __name__)

VERIFIER_OUTCOMES = ("MATCH", "NO_MATCH", "DOCUMENTATION_REQUIRED")


@bp.get("/lifeline/eligibility-checks/<check_id>")
def read_check(check_id):
    authenticate(ROLES_ALL)
    check = get_check(check_id)
    return response.ok(derive.eligibility_check_json(check))


@bp.post("/lifeline/eligibility-checks/<check_id>/verifier-result")
def verifier_result(check_id):
    authenticate((NATIONAL_VERIFIER,))
    check = get_check(check_id)

    body = v.get_body()
    outcome = v.enum_field(body, "verifier_outcome", VERIFIER_OUTCOMES)
    reason_code = v.string_field(body, "verifier_reason_code", required=False,
                                 min_len=0, default=None)
    matched_benefit = v.enum_field(body, "matched_benefit", MATCHED_BENEFITS,
                                   required=False, default=None)
    if (outcome == "MATCH" and check["claimed_basis"] == "BENEFIT"
            and matched_benefit is None):
        v.bad("matched_benefit is required on a MATCH for a benefit-claimed check")

    if check["status"] != "PENDING_VERIFIER":
        raise ApiError("ERR_ELIGIBILITY_CHECK_NOT_PENDING",
                       "A determination has already been posted on this check")

    check["verifier_outcome"] = outcome
    subscriber = db.db.subscribers.get(check["subscriber_id"])

    if outcome == "MATCH":
        check["status"] = "ELIGIBLE_CONFIRMED"
        check["confirmed_at"] = db.now()
        check["expires_at"] = calc.certification_expiry(check["confirmed_at"])
        check["verifier_reason_code"] = reason_code
        check["matched_benefit"] = matched_benefit
        db.touch(check)
        if subscriber is not None:
            if subscriber["status"] == "ELIGIBILITY_PENDING":
                subscriber["status"] = "VERIFIED_ELIGIBLE"
            db.touch(subscriber)
    elif outcome == "NO_MATCH":
        check["status"] = "INELIGIBLE"
        check["verifier_reason_code"] = reason_code
        db.touch(check)
        if subscriber is not None and subscriber["status"] == "ELIGIBILITY_PENDING":
            subscriber["status"] = "PROSPECT"
            db.touch(subscriber)
    else:
        check["status"] = "DOCUMENTATION_REQUIRED"
        check["verifier_reason_code"] = reason_code
        db.touch(check)

    return response.ok(derive.eligibility_check_json(check))


@bp.post("/lifeline/eligibility-checks/<check_id>/resubmit-documentation")
def resubmit_documentation(check_id):
    authenticate((PROVIDER_AGENT,))
    check = get_check(check_id)

    body = v.get_body()
    proof_document_ref = v.string_field(body, "proof_document_ref", min_len=1)

    if check["status"] != "DOCUMENTATION_REQUIRED":
        raise ApiError("ERR_DOCUMENTATION_NOT_REQUESTED",
                       "The check is not awaiting replacement documentation")
    if check["resubmission_count"] >= calc.MAX_DOCUMENTATION_RESUBMISSIONS:
        raise ApiError("ERR_RESUBMISSION_LIMIT_EXCEEDED",
                       "The documentation resubmission limit has been reached")

    check["proof_document_ref"] = proof_document_ref
    check["status"] = "PENDING_VERIFIER"
    check["resubmission_count"] += 1
    check["verifier_outcome"] = None
    check["verifier_reason_code"] = None
    db.touch(check)
    return response.ok(derive.eligibility_check_json(check))
