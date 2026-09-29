"""Proof of loss filing, review, acceptance, and payment reversal."""

from decimal import Decimal

from flask import Blueprint, g

import calc
import errors
import validate
from calc import dec
from cascades import recompute_limit_status, run_waterfall, terminate_claim_engagements
from db import new_row, round2, sorted_by_created, store, touch
from errors import ApiError
from middleware import (CLAIMS_ADJUSTER, INSURED, PORTFOLIO_ACTUARY, UNDERWRITER,
                        endpoint, find_claim, find_payment, find_proof, owner_of_claim,
                        owner_of_payment, owner_of_proof, scope_guard, scoped_filter)
from response import created, listing, ok
from routes.common import apply_eq, filter_value

bp = Blueprint("proofs", __name__, url_prefix="/cyber")


def _interruption_section(claim, policy):
    """The tower section fixed by the claim's incident_type, or None."""
    key = calc.SECTION_FOR_INCIDENT_TYPE.get(claim["incident_type"])
    if key is None:
        return None, None
    return key, calc.section_by_key(policy["id"], key)


def _waiting_period_guard(claim, policy):
    key, section = _interruption_section(claim, policy)
    if section is None:
        raise ApiError(errors.ERR_WAITING_PERIOD_NOT_SATISFIED, 422,
                       "no interruption section responds to this incident type")
    compensable = calc.compensable_hours_of(claim, section)
    if compensable is None or compensable <= 0:
        raise ApiError(errors.ERR_WAITING_PERIOD_NOT_SATISFIED, 422,
                       "the outage does not exceed the section's waiting period")
    return key, section, compensable


# --------------------------------------------------------------------------
# filing
# --------------------------------------------------------------------------

@bp.route("/incident-claims/<claim_id>/proofs-of-loss", methods=["POST"])
@endpoint(roles=[CLAIMS_ADJUSTER, INSURED])
def file_proof(claim_id):
    claim = find_claim(claim_id)
    scope_guard(owner_of_claim(claim))
    payload = validate.body()

    expected = validate.req_int(payload, "expected_claim_version", None, None)
    claimed = validate.req_num(payload, "claimed_bi_loss_usd", minimum=0, money=True)
    trailing = validate.req_num(payload, "trailing_12m_revenue_usd", minimum=0,
                                exclusive_min=True, money=True)
    prior_revenue = validate.req_num(payload, "prior_year_same_period_revenue_usd", minimum=0,
                                     exclusive_min=True, money=True)
    prior_hours = validate.req_num(payload, "prior_year_same_period_hours", minimum=0,
                                   exclusive_min=True)
    margin = validate.req_num(payload, "gross_profit_margin_pct", minimum=0,
                              exclusive_min=True, maximum=1)
    extra = validate.opt_num(payload, "extra_expense_usd", minimum=0, money=True,
                             default=round2(0))
    mitigation = validate.opt_num(payload, "mitigation_savings_usd", minimum=0, money=True,
                                  default=round2(0))

    if expected != claim["version"]:
        raise ApiError(errors.ERR_STALE_CLAIM_VERSION, 412,
                       "expected_claim_version does not match the current version")
    if claim["status"] not in ("COVERAGE_CONFIRMED", "RESPONSE_ACTIVE", "PROOF_REVIEW",
                              "INFO_REQUESTED"):
        raise ApiError(errors.ERR_INVALID_CLAIM_STATE, 409,
                       "a proof of loss may not be filed against a claim in %s"
                       % claim["status"])
    policy = store.policies[claim["policy_id"]]
    _waiting_period_guard(claim, policy)

    for existing in sorted_by_created(calc.proofs_of_claim(claim["id"])):
        if existing["status"] in ("UNDER_REVIEW", "INFO_REQUESTED"):
            existing["status"] = "SUPERSEDED"
            touch(existing)

    proof = new_row({
        "incident_claim_id": claim["id"],
        "claimed_bi_loss_usd": round2(claimed),
        "trailing_12m_revenue_usd": round2(trailing),
        "prior_year_same_period_revenue_usd": round2(prior_revenue),
        "prior_year_same_period_hours": prior_hours,
        "gross_profit_margin_pct": margin,
        "extra_expense_usd": round2(extra),
        "mitigation_savings_usd": round2(mitigation),
        "status": "UNDER_REVIEW",
        "baseline_method_applied": None,
        "outage_hours": None,
        "compensable_hours": None,
        "bi_component_usd": None,
        "mitigation_component_usd": None,
        "extra_expense_component_usd": None,
        "assessed_indemnity_usd": None,
        "info_request_note": None,
    })
    store.proofs_of_loss[proof["id"]] = proof

    claim["status"] = "PROOF_REVIEW"
    touch(claim)
    return created(proof)


@bp.route("/proofs-of-loss/<proof_id>", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, INSURED])
def read_proof(proof_id):
    proof = find_proof(proof_id)
    scope_guard(owner_of_proof(proof))
    return ok(proof)


@bp.route("/proofs-of-loss", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, INSURED])
def list_proofs():
    rows = list(store.proofs_of_loss.values())
    rows = apply_eq(rows, "incident_claim_id", filter_value("incident_claim_id"))
    rows = apply_eq(rows, "status", filter_value("status", calc.PROOF_STATES))
    rows = scoped_filter(rows, owner_of_proof)
    return listing(sorted_by_created(rows))


# --------------------------------------------------------------------------
# information requests
# --------------------------------------------------------------------------

@bp.route("/proofs-of-loss/<proof_id>/request-info", methods=["POST"])
@endpoint(roles=[CLAIMS_ADJUSTER])
def request_proof_info(proof_id):
    proof = find_proof(proof_id)
    payload = validate.body()
    note = validate.req_str(payload, "info_request_note", 1, None)
    if proof["status"] != "UNDER_REVIEW":
        raise ApiError(errors.ERR_INVALID_PROOF_STATE, 409,
                       "only a proof UNDER_REVIEW may be queried")
    claim = store.incident_claims[proof["incident_claim_id"]]
    if claim["status"] != "PROOF_REVIEW":
        raise ApiError(errors.ERR_INVALID_CLAIM_STATE, 409,
                       "the claim is not in PROOF_REVIEW")

    if claim["proof_review_round"] < calc.MAX_PROOF_REVIEW_ROUNDS:
        proof["status"] = "INFO_REQUESTED"
        proof["info_request_note"] = note
        touch(proof)
        claim["status"] = "INFO_REQUESTED"
        claim["proof_review_round"] = claim["proof_review_round"] + 1
        touch(claim)
        return ok(proof)

    # the round past MAX_PROOF_REVIEW_ROUNDS ends the negotiation instead
    proof["status"] = "SUPERSEDED"
    touch(proof)
    claim["status"] = "DENIED"
    claim["denial_reason"] = "PROOF_INSUFFICIENT"
    claim["reserved_amount_usd"] = round2(0)
    touch(claim)
    terminate_claim_engagements(claim)
    return ok(proof)


# --------------------------------------------------------------------------
# acceptance
# --------------------------------------------------------------------------

@bp.route("/proofs-of-loss/<proof_id>/accept", methods=["POST"])
@endpoint(roles=[CLAIMS_ADJUSTER])
def accept_proof(proof_id):
    proof = find_proof(proof_id)
    claim = store.incident_claims[proof["incident_claim_id"]]
    for engagement in calc.engagements_of_claim(claim["id"]):
        if engagement["authorized_by_user_id"] == g.user_id:
            raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                           "the adjuster who authorised a panel firm may not accept the proof")
    payload = validate.body()
    override = validate.opt_enum(payload, "baseline_method_override", calc.BASELINE_METHODS)

    if proof["status"] != "UNDER_REVIEW":
        raise ApiError(errors.ERR_INVALID_PROOF_STATE, 409,
                       "only a proof UNDER_REVIEW may be accepted")
    if claim["status"] != "PROOF_REVIEW":
        raise ApiError(errors.ERR_INVALID_CLAIM_STATE, 409,
                       "the claim is not in PROOF_REVIEW")
    policy = store.policies[claim["policy_id"]]
    if policy["lifecycle_status"] != "INFORCE":
        raise ApiError(errors.ERR_INVALID_POLICY_STATE, 409,
                       "the responding policy is no longer INFORCE")

    key, section, _hours = _waiting_period_guard(claim, policy)
    if key not in (claim["covered_section_keys"] or []):
        raise ApiError(errors.ERR_NO_ELIGIBLE_COVERAGE_SECTION, 422,
                       "%s was not confirmed as a responding section" % key)
    if dec(policy["aggregate_limit_remaining_usd"]) <= 0:
        raise ApiError(errors.ERR_AGGREGATE_LIMIT_EXHAUSTED, 422,
                       "the policy aggregate limit is exhausted")

    applied = override or policy["bi_baseline_method"]
    figures = calc.bi_indemnity_quantification(claim, proof, section, applied)

    # hop 1
    proof["status"] = "ACCEPTED"
    proof["baseline_method_applied"] = applied
    proof["outage_hours"] = figures["outage_hours"]
    proof["compensable_hours"] = figures["compensable_hours"]
    proof["bi_component_usd"] = figures["bi_component_usd"]
    proof["mitigation_component_usd"] = figures["mitigation_component_usd"]
    proof["extra_expense_component_usd"] = figures["extra_expense_component_usd"]
    proof["assessed_indemnity_usd"] = figures["assessed_indemnity_usd"]
    touch(proof)

    # hop 2
    claim["status"] = "APPROVED_FOR_PAYMENT"
    touch(claim)

    # hops 3-6
    run_waterfall(claim, policy, figures["assessed_indemnity_usd"], [key], "PROOF_OF_LOSS")
    claim["reserved_amount_usd"] = round2(0)
    claim["status"] = "SETTLED"
    touch(claim)
    return ok(proof)


# --------------------------------------------------------------------------
# claim payments
# --------------------------------------------------------------------------

@bp.route("/claim-payments/<payment_id>", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, INSURED])
def read_payment(payment_id):
    payment = find_payment(payment_id)
    scope_guard(owner_of_payment(payment))
    return ok(payment)


@bp.route("/claim-payments", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, INSURED])
def list_payments():
    rows = list(store.claim_payments.values())
    rows = apply_eq(rows, "incident_claim_id", filter_value("incident_claim_id"))
    rows = apply_eq(rows, "coverage_section_id", filter_value("coverage_section_id"))
    rows = apply_eq(rows, "loss_source", filter_value("loss_source", calc.LOSS_SOURCES))
    rows = apply_eq(rows, "payment_status", filter_value("payment_status", calc.PAYMENT_STATES))
    rows = scoped_filter(rows, owner_of_payment)
    return listing(sorted_by_created(rows))


@bp.route("/claim-payments/<payment_id>/reverse", methods=["POST"])
@endpoint(roles=[CLAIMS_ADJUSTER])
def reverse_payment(payment_id):
    payment = find_payment(payment_id)
    payload = validate.body()
    reason = validate.req_str(payload, "reversal_reason", 1, None)
    if payment["payment_status"] != "POSTED":
        raise ApiError(errors.ERR_INVALID_PAYMENT_STATE, 409,
                       "only a POSTED payment row may be reversed")
    claim = store.incident_claims[payment["incident_claim_id"]]
    policy = store.policies[claim["policy_id"]]
    if policy["lifecycle_status"] == "CANCELLED":
        raise ApiError(errors.ERR_INVALID_POLICY_STATE, 409,
                       "a payment on a cancelled policy may not be reversed")

    payment["payment_status"] = "REVERSED"
    payment["reversal_reason"] = reason
    touch(payment)

    section = store.coverage_sections.get(payment["coverage_section_id"])
    if section is not None:
        section["sublimit_remaining_usd"] = round2(
            dec(section["sublimit_remaining_usd"]) + dec(payment["gross_amount_usd"]))
        touch(section)
    policy["aggregate_limit_remaining_usd"] = round2(
        dec(policy["aggregate_limit_remaining_usd"]) + dec(payment["net_paid_usd"]))
    touch(policy)
    recompute_limit_status(policy)

    claim["paid_total_usd"] = round2(dec(claim["paid_total_usd"]) - dec(payment["net_paid_usd"]))
    claim["retention_absorbed_usd"] = round2(
        max(Decimal("0"), dec(claim["retention_absorbed_usd"])
            - dec(payment["retention_applied_usd"])))
    claim["unallocated_loss_usd"] = round2(0)
    if claim["status"] == "SETTLED":
        claim["status"] = "APPROVED_FOR_PAYMENT"
    touch(claim)
    return ok(payment)
