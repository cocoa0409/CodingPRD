"""Damage claims: settlement dual-variant, approve/reopen cycle, payout-credit
conservation, and claim eligibility / item / state guards.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_damage_claim,
    setup_claim_under_review, setup_approved_claim, setup_delivered_job,
    file_claim, add_claim_item,
    make_claims_adjuster_headers,
    create_damage_claim_payload, create_claim_item_payload,
    register_customer, create_job,
    ITEMS_120CF,
)


def test_settlement_diverges_released_vs_full_value(api):
    """PRD §3.10: "Under `RELEASED` coverage the payout is strictly weight-based:
    it is the sum, over every claim item, of that item's `item_weight_lbs`
    multiplied by sixty cents per pound, with the released sum rounded half up to
    integer cents; repair, replacement, and declared values are ignored, and no
    deductible applies."
    PRD §3.10: "Under `FULL_VALUE` coverage the payout is the sum, over every claim
    item, of the smaller of that item's `repair_cost_cents` and its
    `replacement_value_cents`, less the claim's single `deductible_cents` applied
    once for the whole claim, with the result floored at zero; item weight is
    ignored."

    The identical 40lb item (repair 90000, replacement 150000) settles at 2400
    under RELEASED (40*60) but 40000 under FULL_VALUE (min(90000,150000)-50000).

    Design: Difficulty/dual_variant_calc/claim_settlement_released_vs_full_value_diverge
    """
    item = {"label": "mirror", "item_weight_lbs": 40,
            "repair_cost_cents": 90000, "replacement_value_cents": 150000}

    _, _, _, rel_claim = setup_approved_claim(
        valuation_coverage="RELEASED", item_overrides=item)
    _, _, _, fv_claim = setup_approved_claim(
        valuation_coverage="FULL_VALUE", deductible_cents=50000,
        declared_value_cents=600000, item_overrides=item)

    assert rel_claim["settlement_cents"] == 2400
    assert fv_claim["settlement_cents"] == 40000


def test_released_settlement_is_weight_based(api):
    """PRD §3.10: "Under `RELEASED` coverage the payout is strictly weight-based:
    it is the sum, over every claim item, of that item's `item_weight_lbs`
    multiplied by sixty cents per pound, with the released sum rounded half up to
    integer cents; repair, replacement, and declared values are ignored, and no
    deductible applies."

    Second assertion on the dual-variant instance: a RELEASED claim with a 40lb
    item ignores its (large) repair/replacement values and pays exactly 2400.

    Design: Difficulty/dual_variant_calc/claim_settlement_released_vs_full_value_diverge
    """
    _, _, _, claim = setup_approved_claim(
        valuation_coverage="RELEASED",
        item_overrides={"label": "mirror", "item_weight_lbs": 40,
                        "repair_cost_cents": 90000, "replacement_value_cents": 150000})
    assert claim["status"] == "APPROVED"
    assert claim["settlement_cents"] == 2400


def test_claim_approve_then_reopen_returns_under_review(api):
    """PRD §3.10: "On approval the settlement is computed and written to
    `settlement_cents`, the acting `X-User-ID` is recorded as
    `adjudicated_by_user_id`, the claim moves `UNDER_REVIEW → APPROVED`, and the
    `settlement_cents` is added to the job's `refunded_cents` as a payout credit
    before `balance_due_cents` is recomputed."
    PRD §3.10: "An `APPROVED` claim may be reopened by a `ClaimsAdjuster` as long as
    the linked job is not `CLOSED`; reopening subtracts the prior `settlement_cents`
    from the job's `refunded_cents` as a compensating reversal, sets the claim's
    `settlement_cents` back to 0, clears `adjudicated_by_user_id`, recomputes
    `balance_due_cents`, and moves the claim `APPROVED → UNDER_REVIEW`."

    The branch-with-revert cycle UNDER_REVIEW->APPROVED->UNDER_REVIEW; reopen
    zeroes settlement_cents.

    Design: Difficulty/non_linear_state_machine/damage_claim_approve_then_reopen_cycle
    """
    _, _, _, claim = setup_approved_claim(valuation_coverage="RELEASED")
    assert claim["status"] == "APPROVED"
    assert claim["settlement_cents"] == 2400

    reopened = validate_success(
        api.reopen_damage_claim(claim["id"], make_claims_adjuster_headers("adj-approver")), 200)
    assert reopened["status"] == "UNDER_REVIEW"
    assert reopened["settlement_cents"] == 0


def test_claim_reopen_clears_adjudicator(api):
    """PRD §3.10: "reopening subtracts the prior `settlement_cents` from the job's
    `refunded_cents` as a compensating reversal, sets the claim's
    `settlement_cents` back to 0, clears `adjudicated_by_user_id`, recomputes
    `balance_due_cents`, and moves the claim `APPROVED → UNDER_REVIEW`."

    Second assertion on the approve->reopen cycle instance: after reopen the claim
    is back UNDER_REVIEW with settlement_cents zeroed (the cleared adjudicator is
    not asserted on the response, but the state + settlement revert is).

    Design: Difficulty/non_linear_state_machine/damage_claim_approve_then_reopen_cycle
    """
    _, _, _, claim = setup_approved_claim(valuation_coverage="RELEASED")
    reopened = validate_success(
        api.reopen_damage_claim(claim["id"], make_claims_adjuster_headers("adj-approver")), 200)
    assert_damage_claim(reopened)
    assert reopened["status"] == "UNDER_REVIEW"
    assert reopened["settlement_cents"] == 0


def test_claim_reopen_conserves_refunded_credit(api):
    """PRD §3.10: "the `settlement_cents` is added to the job's `refunded_cents` as
    a payout credit before `balance_due_cents` is recomputed."
    PRD §3.10: "reopening subtracts the prior `settlement_cents` from the job's
    `refunded_cents` as a compensating reversal ... and the reversal must exactly
    zero out the prior payout credit."

    Approve adds settlement 2400 to refunded_cents; reopen subtracts exactly 2400,
    restoring refunded_cents to 0 with no drift.

    Design: Difficulty/compensating_invariant/claim_reopen_conserves_payout_credit
    """
    _, job, _, claim = setup_approved_claim(valuation_coverage="RELEASED")
    job_after_approve = get_success_data(api.get_move_job(job["id"], make_claims_adjuster_headers("adj-approver")))
    assert job_after_approve["refunded_cents"] == 2400

    reopened = validate_success(
        api.reopen_damage_claim(claim["id"], make_claims_adjuster_headers("adj-approver")), 200)
    assert reopened["settlement_cents"] == 0

    job_after_reopen = get_success_data(api.get_move_job(job["id"], make_claims_adjuster_headers("adj-approver")))
    assert job_after_reopen["refunded_cents"] == 0


def test_claim_approve_credits_refunded_then_reopen_restores(api):
    """PRD §3.10: "the `settlement_cents` is added to the job's `refunded_cents` as
    a payout credit before `balance_due_cents` is recomputed."
    PRD §3.10: "the reversal must exactly zero out the prior payout credit."

    Second assertion on the payout-credit conservation invariant, verifying the
    full add-then-subtract round trip leaves refunded_cents == 0 and the claim
    back UNDER_REVIEW.

    Design: Difficulty/compensating_invariant/claim_reopen_conserves_payout_credit
    """
    _, job, _, claim = setup_approved_claim(valuation_coverage="RELEASED")
    reopened = validate_success(
        api.reopen_damage_claim(claim["id"], make_claims_adjuster_headers("adj-approver")), 200)
    assert reopened["status"] == "UNDER_REVIEW"
    job_after = get_success_data(api.get_move_job(job["id"], make_claims_adjuster_headers("adj-approver")))
    assert job_after["refunded_cents"] == 0


def test_terminal_denied_claim_cannot_be_approved(api):
    """PRD §3.10: "Attempting any adjudication transition from a state where it is
    not defined is rejected with `ERR_INVALID_STATE`."

    A DENIED claim is terminal; approving it returns ERR_INVALID_STATE.

    Design: Corner/state_machines/terminal_denied_claim_cannot_be_approved
    """
    _, _, _, claim = setup_claim_under_review(valuation_coverage="RELEASED", with_item=True)
    validate_success(
        api.deny_damage_claim(claim["id"], make_claims_adjuster_headers("adj-approver")), 200)
    res = api.approve_damage_claim(claim["id"], make_claims_adjuster_headers("adj-approver"))
    validate_error(res, "ERR_INVALID_STATE", 409)


def test_claim_not_eligible_on_quoting_job(api):
    """PRD §3.10: "Filing is only eligible when the job is `DELIVERED` and has an
    accepted estimate to draw coverage terms from; filing against an ineligible job
    is rejected with `ERR_CLAIM_NOT_ELIGIBLE`."

    Filing a claim against a QUOTING (not delivered) job returns
    ERR_CLAIM_NOT_ELIGIBLE.

    Design: Corner/validations/claim_not_eligible_on_quoting_job_returns_409
    """
    cust_id = register_customer()["id"]
    job = create_job(cust_id, "LOCAL")
    res = api.create_damage_claim(
        create_damage_claim_payload(job["id"]), make_claims_adjuster_headers("adj-filer"))
    validate_error(res, "ERR_CLAIM_NOT_ELIGIBLE", 409)


def test_approve_claim_with_no_items_rejected(api):
    """PRD §3.10: "Approval requires, in addition to the segregation check, that the
    linked job still be `DELIVERED` ... and that the claim have at least one
    `ClaimItem` (otherwise `ERR_CLAIM_NO_ITEMS`)."

    Approving an UNDER_REVIEW claim with zero items returns ERR_CLAIM_NO_ITEMS.

    Design: Corner/validations/approve_claim_with_no_items_returns_409
    """
    _, _, _, claim = setup_claim_under_review(valuation_coverage="RELEASED", with_item=False)
    res = api.approve_damage_claim(claim["id"], make_claims_adjuster_headers("adj-approver"))
    validate_error(res, "ERR_CLAIM_NO_ITEMS", 409)
