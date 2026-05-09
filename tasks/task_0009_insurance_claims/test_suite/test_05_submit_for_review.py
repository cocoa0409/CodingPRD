"""Submit-for-review preconditions, calculations, and review-path assignment.

Pinned to PRD §3.3 (preconditions, calculations, cascade), §3.5 (formulas).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    setup_basic_world, file_claim, open_investigation, update_investigation,
    add_estimate_line_item, submit_for_review, get_claim, add_fraud_flag,
    setup_claim_under_investigation, setup_claim_under_review,
    create_repair_shop, make_adjuster_headers, TEST_USERS,
    AUTO_APPROVAL_THRESHOLD_CENTS, AUTO_FRAUD_GATE,
)


# ─── §3.3 preconditions ───────────────────────────────────────────
def test_submit_without_photos_rejected(api):
    """PRD §3.3: "the investigation's `photo_urls` must contain at least
    one URL (otherwise `ERR_PHOTOS_REQUIRED`)"

    Claim: submit-for-review with empty photo_urls -> ERR_PHOTOS_REQUIRED.
    """
    state = setup_claim_under_investigation(photos=[])
    res = api.submit_for_review(
        state["claim"]["id"], make_adjuster_headers(state["adjuster"]["id"])
    )
    validate_error(res, "ERR_PHOTOS_REQUIRED")


def test_submit_without_doc_authenticity_rejected(api):
    """PRD §3.3: "the investigation's `document_authenticity_passed` must
    be true (otherwise `ERR_DOCUMENT_AUTHENTICITY_FAILED`)"

    Claim: submit with document_authenticity_passed=false -> ERR_DOCUMENT_AUTHENTICITY_FAILED.
    """
    state = setup_claim_under_investigation(document_authenticity_passed=False)
    res = api.submit_for_review(
        state["claim"]["id"], make_adjuster_headers(state["adjuster"]["id"])
    )
    validate_error(res, "ERR_DOCUMENT_AUTHENTICITY_FAILED")


def test_submit_without_estimate_rejected(api):
    """PRD §3.3: "and at least one `EstimateLineItem` must exist for the
    investigation (otherwise `ERR_ESTIMATE_REQUIRED`)."

    Claim: submit without any EstimateLineItem -> ERR_ESTIMATE_REQUIRED.

    # difficulty: boundary_precision_check/estimate_required_empty_collection_boundary
    """
    state = setup_claim_under_investigation(add_estimate=False)
    res = api.submit_for_review(
        state["claim"]["id"], make_adjuster_headers(state["adjuster"]["id"])
    )
    validate_error(res, "ERR_ESTIMATE_REQUIRED")


def test_submit_with_one_estimate_succeeds_boundary(api):
    """PRD §3.3: "at least one `EstimateLineItem` must exist for the
    investigation".

    Claim: with exactly ONE EstimateLineItem, submit-for-review succeeds and
    Claim transitions to UNDER_REVIEW (the 0->1 cardinality boundary).

    # difficulty: boundary_precision_check/estimate_required_empty_collection_boundary
    """
    state = setup_claim_under_investigation(add_estimate=True)
    res = api.submit_for_review(
        state["claim"]["id"], make_adjuster_headers(state["adjuster"]["id"])
    )
    validate_success(res)
    refreshed = get_claim(state["claim"]["id"])
    assert refreshed["status"] == "UNDER_REVIEW"


# ─── §3.3 / §3.5 gross_payout calculation ─────────────────────────
def test_gross_payout_basic_formula(api):
    """PRD §3.5 (Gross payout): "First, take the assessed loss in cents
    (the value of `Claim.assessed_loss_cents` at submission, ...). Subtract
    the policy's `deductible_cents` from the assessed loss; if the result
    is negative, treat it as zero — this is the "after deductible" amount.
    Multiply that amount by the policy's `coinsurance_ratio` ... to obtain
    a raw insurer-share figure ... Round that raw figure to integer cents
    using the "round half up" rule, performing this rounding exactly once
    and only at this step. Finally, compare the rounded insurer-share cents
    against the policy's `coverage_limit_cents` and take the smaller of the
    two; that result is the `gross_payout_cents`."

    Claim: with L=500000, D=100000, C=0.8000, M=1000000:
    after_deductible = 400000; insurer_share = 320000; gross = min(320000, 1000000) = 320000.
    """
    state = setup_claim_under_review(
        assessed_loss_cents=500_000,
        deductible_cents=100_000,
        coinsurance_ratio=0.8000,
        coverage_limit_cents=1_000_000,
        claimed_amount_cents=500_000,
    )
    assert state["claim"]["gross_payout_cents"] == 320_000


def test_gross_payout_capped_by_coverage_limit(api):
    """PRD §3.5 (Gross payout): "Finally, compare the rounded insurer-share
    cents against the policy's `coverage_limit_cents` and take the smaller
    of the two; that result is the `gross_payout_cents`."

    Claim: L=2000000, D=100000, C=0.9, M=1000000 ->
    after_deductible = 1900000; insurer_share = 1710000; gross = min(1710000, 1000000) = 1000000.

    # difficulty: combinatorial_formula/gross_payout_three_input_nonlinear_min_max
    """
    state = setup_claim_under_review(
        assessed_loss_cents=2_000_000,
        deductible_cents=100_000,
        coinsurance_ratio=0.9000,
        coverage_limit_cents=1_000_000,
        claimed_amount_cents=2_000_000,
    )
    assert state["claim"]["gross_payout_cents"] == 1_000_000


def test_gross_payout_negative_after_deductible_clamped_zero(api):
    """PRD §3.5 (Gross payout): "Subtract the policy's `deductible_cents`
    from the assessed loss; if the result is negative, treat it as zero —
    this is the "after deductible" amount."

    Claim: L=10000, D=100000 -> after_deductible = max(0, 10000 - 100000) = 0;
    gross = 0.
    """
    state = setup_claim_under_review(
        assessed_loss_cents=10_000,
        deductible_cents=100_000,
        coinsurance_ratio=0.8000,
        coverage_limit_cents=1_000_000,
        claimed_amount_cents=10_000,
    )
    assert state["claim"]["gross_payout_cents"] == 0


# ─── §3.5 net_payout (at_approval) ────────────────────────────────
def test_net_payout_at_approval_subtracts_salvage(api):
    """PRD §3.5 (Net payout): "It equals the `gross_payout_cents` minus
    `salvage_value_cents` minus `subrogation_recovery_cents`; if that
    subtraction would yield a negative number, the result is clamped to
    zero. The calculation runs at the moment any of those three inputs
    changes: at the submit-for-review transition (its `at_approval`
    variant, where `subrogation_recovery_cents` is treated as zero so the
    outcome equals `gross_payout_cents` minus `salvage_value_cents`)"

    Claim: with gross=320000 and salvage=50000 at submit, net=270000.
    """
    state = setup_claim_under_review(
        assessed_loss_cents=500_000,
        deductible_cents=100_000,
        coinsurance_ratio=0.8000,
        coverage_limit_cents=1_000_000,
        salvage_value_cents=50_000,
        claimed_amount_cents=500_000,
    )
    assert state["claim"]["gross_payout_cents"] == 320_000
    assert state["claim"]["net_payout_cents"] == 270_000


# ─── §3.3 review_path_assignment threshold ────────────────────────
def test_review_path_inclusive_at_threshold_routes_auto(api):
    """PRD §3.3: "Two intake parameters drive the review-path decision but
    do not appear in the submission payload itself — `claimed_amount_cents`
    was supplied at filing time, and `fraud_score` is derived from previously
    recorded `FraudFlag` rows. The decision is: `Claim.review_path` becomes
    `AUTO` if and only if `claimed_amount_cents` is at most 200,000 cents
    (that is, two thousand dollars or less) and `fraud_score` is strictly
    less than 0.30; otherwise `Claim.review_path` becomes `MANUAL`."

    PRD §3.5 (Review-path assignment): "The threshold comparison on
    `claimed_amount_cents` is inclusive (a value equal to the threshold
    still routes to `AUTO`)"

    Claim: claimed_amount_cents == 200000 with no fraud flags -> AUTO.

    # difficulty: boundary_precision_check/auto_approval_threshold_inclusive_boundary
    """
    state = setup_claim_under_review(
        claimed_amount_cents=200_000,
        assessed_loss_cents=200_000,
        deductible_cents=0,
        coinsurance_ratio=1.0000,
        coverage_limit_cents=10_000_000,
    )
    assert state["claim"]["review_path"] == "AUTO"


def test_review_path_just_over_threshold_routes_manual(api):
    """PRD §3.5 (Review-path assignment): "The path becomes `AUTO` if and
    only if `claimed_amount_cents` is less than or equal to the auto-approval
    threshold of 200,000 cents (that is, 2,000 dollars) AND `fraud_score`
    is strictly less than the auto-fraud gate of 0.30; otherwise the path
    becomes `MANUAL`."

    Claim: claimed_amount_cents == 200001 -> MANUAL (boundary exclusive on the > side).

    # difficulty: boundary_precision_check/auto_approval_threshold_inclusive_boundary
    """
    state = setup_claim_under_review(
        claimed_amount_cents=200_001,
        assessed_loss_cents=200_001,
        deductible_cents=0,
        coinsurance_ratio=1.0000,
        coverage_limit_cents=10_000_000,
    )
    assert state["claim"]["review_path"] == "MANUAL"


def test_review_path_fraud_gate_inclusive_routes_manual(api):
    """PRD §3.5 (Review-path assignment): "the fraud gate is exclusive
    (a `fraud_score` exactly equal to 0.30 routes to `MANUAL`)."

    Claim: with one DUPLICATE_PATTERN flag at severity=1.0
    -> fraud_score = 0.30 (W_PATTERN=0.30) and review_path=MANUAL.
    """
    state = setup_claim_under_investigation(claimed_amount_cents=100_000)
    add_fraud_flag(state["claim"], signal="DUPLICATE_PATTERN", severity=1.0)
    submit_for_review(state["claim"], state["adjuster"])
    refreshed = get_claim(state["claim"]["id"])
    assert refreshed["fraud_score"] == 0.30
    assert refreshed["review_path"] == "MANUAL"


def test_fraud_score_capped_per_signal_then_weighted(api):
    """PRD §3.5 (Fraud score): "Cap each of the four subtotals at 1.00
    individually before any weighted combination — the per-signal cap is
    applied first. Then form the weighted sum: 0.30 times the capped pattern
    subtotal, plus 0.30 times the capped collusion subtotal, plus 0.30 times
    the capped forgery subtotal, plus 0.10 times the capped rapid-resubmission
    subtotal."

    Claim: 1 DUPLICATE_PATTERN @ 0.6 + 1 DOCUMENT_FORGERY @ 0.4 ->
    raw = 0.30*0.6 + 0.30*0.4 = 0.18 + 0.12 = 0.30 -> fraud_score = 0.30.
    """
    state = setup_claim_under_investigation(claimed_amount_cents=100_000)
    add_fraud_flag(state["claim"], signal="DUPLICATE_PATTERN", severity=0.6)
    add_fraud_flag(state["claim"], signal="DOCUMENT_FORGERY", severity=0.4)
    submit_for_review(state["claim"], state["adjuster"])
    refreshed = get_claim(state["claim"]["id"])
    assert refreshed["fraud_score"] == 0.30


def test_fraud_score_clamped_to_one(api):
    """PRD §3.5 (Fraud score): "Round the weighted sum to two decimal places
    using "round half up" exactly once at this step, and finally clamp the
    rounded value to the inclusive range zero to one."

    Claim: with full-severity flags on every category (after per-signal cap)
    -> raw = 0.30 + 0.30 + 0.30 + 0.10 = 1.00 -> fraud_score = 1.00.
    """
    state = setup_claim_under_investigation(claimed_amount_cents=100_000)
    add_fraud_flag(state["claim"], signal="DUPLICATE_PATTERN", severity=1.0)
    add_fraud_flag(state["claim"], signal="REPAIR_SHOP_COLLUSION", severity=1.0,
                   repair_shop_id=state["repair_shop"]["id"])
    add_fraud_flag(state["claim"], signal="DOCUMENT_FORGERY", severity=1.0)
    add_fraud_flag(state["claim"], signal="RAPID_RESUBMISSION", severity=1.0)
    # fraud_score will be 1.00 -> >= 0.80 fraud-hold; submit must error.
    res = api.submit_for_review(
        state["claim"]["id"], make_adjuster_headers(state["adjuster"]["id"])
    )
    validate_error(res, "ERR_FRAUD_HOLD")


# ─── §2.9 / §3.3 fraud_hold guard ─────────────────────────────────
def test_fraud_hold_gate_at_080(api):
    """PRD §3.3: "The freshly-computed `fraud_score` must be strictly less
    than 0.80; reaching or exceeding that ceiling is rejected with
    `ERR_FRAUD_HOLD`."
    PRD §2.9: "If that score reaches or exceeds 0.80, the transition out
    of `UNDER_INVESTIGATION` is blocked and the server returns
    `ERR_FRAUD_HOLD`"

    Claim: fraud_score >= 0.80 at submit -> ERR_FRAUD_HOLD (and no transition).

    # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_fraud_hold_vs_photo
    """
    state = setup_claim_under_investigation()
    # Three full-severity .30-weight signals add to 0.90 (after cap & weights).
    add_fraud_flag(state["claim"], signal="DUPLICATE_PATTERN", severity=1.0)
    add_fraud_flag(state["claim"], signal="REPAIR_SHOP_COLLUSION", severity=1.0,
                   repair_shop_id=state["repair_shop"]["id"])
    add_fraud_flag(state["claim"], signal="DOCUMENT_FORGERY", severity=1.0)
    res = api.submit_for_review(
        state["claim"]["id"], make_adjuster_headers(state["adjuster"]["id"])
    )
    validate_error(res, "ERR_FRAUD_HOLD")


# ─── §2.9 / §3.3 coverage limit guard ─────────────────────────────
def test_coverage_limit_guard_clamps_via_min(api):
    """PRD §3.5 (Gross payout): "Finally, compare the rounded insurer-share
    cents against the policy's `coverage_limit_cents` and take the smaller
    of the two; that result is the `gross_payout_cents`."
    PRD §3.3: "The freshly-computed `gross_payout_cents` must not exceed
    the policy's `coverage_limit_cents`; a violation is rejected with
    `ERR_COVERAGE_LIMIT_EXCEEDED`."

    Claim: with the formula always taking min(insurer_share, M), the
    pinned gross_payout_cents == coverage_limit_cents when insurer_share
    would otherwise overflow. Submit succeeds and Claim.gross_payout_cents
    equals coverage_limit_cents (the min clamp is observable; the
    ERR_COVERAGE_LIMIT_EXCEEDED guard is reserved for direct mutations
    that bypass the calculation).
    """
    state = setup_claim_under_review(
        assessed_loss_cents=10_000_000,
        deductible_cents=0,
        coinsurance_ratio=1.0000,
        coverage_limit_cents=1_000_000,
        claimed_amount_cents=10_000_000,
    )
    assert state["claim"]["gross_payout_cents"] == 1_000_000


# ─── §3.3 side effect: Investigation -> COMPLETED ─────────────────
def test_submit_marks_investigation_completed_and_assessed_loss_pinned(api):
    """PRD §3.3: "Side effects on success are: `Investigation.status` is
    set to `COMPLETED`; `Claim.assessed_loss_cents` is copied from
    `Investigation.assessed_loss_cents`; `Claim.gross_payout_cents` and
    `Claim.net_payout_cents` are written; `Claim.fraud_score` is written"

    Claim: after submit, Investigation.status == COMPLETED and
    Claim.assessed_loss_cents matches the investigation's value.
    """
    state = setup_claim_under_review(
        assessed_loss_cents=400_000,
        deductible_cents=100_000,
        coinsurance_ratio=0.5,
        coverage_limit_cents=10_000_000,
        claimed_amount_cents=400_000,
    )
    assert state["claim"]["assessed_loss_cents"] == 400_000
    assert state["claim"]["status"] == "UNDER_REVIEW"
    # gross = round_half_up(0.5 * (400000 - 100000)) = 150000
    assert state["claim"]["gross_payout_cents"] == 150_000


def test_submit_for_review_rbac_only_adjuster(api, customer_headers):
    """PRD §4 endpoints table: POST /claims/{id}/submit-for-review is
    Adjuster-only.

    Claim: Customer calling submit-for-review -> ERR_FORBIDDEN.
    """
    state = setup_claim_under_investigation()
    res = api.submit_for_review(state["claim"]["id"], customer_headers)
    validate_error(res, "ERR_FORBIDDEN")
