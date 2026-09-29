"""The qualification fork: the insurance arm, the capability arm and the decision —
PRD §3.1."""
from flask import Blueprint

import auth
import helpers
import responses
import store
import validators as v
from errors import ApiError
from numeric import q2
from services import scoring

bp = Blueprint("reviews", __name__)

DECISION_OUTCOMES = ("APPROVE", "APPROVE_CONDITIONAL", "REMEDIATE", "REJECT")


def _join(review):
    """The review advances to SCREENED at the moment the second arm records a
    non-PENDING result; a review in REMEDIATION returns to SUBMITTED."""
    both_done = (review["insurance_result"] != "PENDING"
                 and review["capability_result"] != "PENDING")
    review["status"] = "SCREENED" if both_done else "SUBMITTED"


@bp.post("/freight-procurement/qualification-reviews/<review_id>/insurance-verification")
@auth.roles_required("ComplianceOfficer")
def insurance_verification(review_id):
    review = helpers.get_review(review_id)
    payload = v.body()
    auto = v.dec_field(payload, "verified_auto_liability_usd")
    cargo = v.dec_field(payload, "verified_cargo_usd")
    expiry = v.dt_field(payload, "verified_expiry_date")

    if review["insurance_result"] != "PENDING":
        raise ApiError("ERR_REVIEW_NOT_SCREENED")

    carrier = store.carriers.get(review["carrier_id"])
    passed = (auto >= review["min_auto_liability_usd"]
              and cargo >= review["min_cargo_usd"]
              and store.parse_dt(expiry) > store.now())

    review["verified_auto_liability_usd"] = q2(auto)
    review["verified_cargo_usd"] = q2(cargo)
    review["verified_expiry_date"] = expiry
    review["insurance_result"] = "PASS" if passed else "FAIL"
    review["insurance_verified_at"] = store.now_iso()
    _join(review)
    store.touch(review)

    if passed and carrier is not None:
        carrier["auto_liability_limit_usd"] = q2(auto)
        carrier["cargo_limit_usd"] = q2(cargo)
        carrier["insurance_expiry_date"] = expiry
        store.touch(carrier)
    return responses.ok(review)


@bp.post("/freight-procurement/qualification-reviews/<review_id>/capability-screening")
@auth.roles_required("ComplianceOfficer")
def capability_screening(review_id):
    review = helpers.get_review(review_id)
    v.body()

    if review["capability_result"] != "PENDING":
        raise ApiError("ERR_REVIEW_NOT_SCREENED")

    carrier = store.carriers.get(review["carrier_id"])
    score = scoring.capability_score(carrier, review)
    covered = set(review["required_modes"]).issubset(set(carrier["service_modes"]))
    review["capability_score"] = score
    review["capability_result"] = ("PASS" if covered
                                   and score >= scoring.CAPABILITY_PASS_FLOOR else "FAIL")
    review["capability_screened_at"] = store.now_iso()
    _join(review)
    store.touch(review)

    carrier["capability_score"] = score
    store.touch(carrier)
    return responses.ok(review)


@bp.post("/freight-procurement/qualification-reviews/<review_id>/decision")
@auth.roles_required("ComplianceOfficer")
def decide(review_id):
    review = helpers.get_review(review_id)
    payload = v.body()
    outcome = payload.get("decision_outcome", payload.get("outcome"))
    if outcome is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'outcome' is required.")
    if not isinstance(outcome, str) or outcome not in DECISION_OUTCOMES:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'outcome' must be one of %s." % ", ".join(DECISION_OUTCOMES))
    note = v.string_field(payload, "decision_note", required=False, default=None)

    if review["status"] != "SCREENED":
        raise ApiError("ERR_REVIEW_NOT_SCREENED")

    if outcome == "APPROVE" and not (review["insurance_result"] == "PASS"
                                     and review["capability_result"] == "PASS"):
        raise ApiError("ERR_REVIEW_NOT_SCREENED")
    if outcome == "APPROVE_CONDITIONAL" and not (review["insurance_result"] == "PASS"
                                                 and review["capability_result"] == "FAIL"):
        raise ApiError("ERR_REVIEW_NOT_SCREENED")
    if (outcome == "REMEDIATE"
            and review["remediation_count"] >= scoring.MAX_REMEDIATIONS):
        raise ApiError("ERR_REMEDIATION_LIMIT_EXCEEDED")

    carrier = store.carriers.get(review["carrier_id"])
    review["decision_outcome"] = outcome
    review["decision_note"] = note
    review["decision_by_user_id"] = auth.actor()

    if outcome == "APPROVE":
        review["status"] = "APPROVED"
        carrier["status"] = "QUALIFIED"
        carrier["capability_score"] = review["capability_score"]
        carrier["qualified_at"] = store.now_iso()
        scoring.recompute_composite(carrier)
        store.touch(carrier)
    elif outcome == "APPROVE_CONDITIONAL":
        review["status"] = "CONDITIONALLY_APPROVED"
        carrier["status"] = "CONDITIONALLY_QUALIFIED"
        carrier["capability_score"] = review["capability_score"]
        carrier["qualified_at"] = store.now_iso()
        scoring.recompute_composite(carrier)
        store.touch(carrier)
    elif outcome == "REMEDIATE":
        review["status"] = "REMEDIATION"
        review["remediation_count"] += 1
        review["insurance_result"] = "PENDING"
        review["capability_result"] = "PENDING"
    else:
        review["status"] = "REJECTED"
        carrier["status"] = "DISQUALIFIED"
        carrier["status_reason"] = note
        store.touch(carrier)

    store.touch(review)
    return responses.ok(review)
