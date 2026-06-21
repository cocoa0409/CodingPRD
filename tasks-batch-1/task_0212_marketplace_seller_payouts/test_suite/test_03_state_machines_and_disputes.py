"""Non-linear state machines: the cyclic A-to-Z dispute, the Order's parallel
settlement/clawback dimensions, dispute-grant cascade, and refund idempotency.

Translates queue A (Difficulty) non_linear_state_machine and several queue B
(Corner) state_machines instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_fee_schedule, create_seller, create_order, create_media_schedule,
    create_requested_refund, apply_refund,
    dispute_cycled, dispute_in_under_review,
    set_clock,
    make_seller_headers,
)
from test_helpers import api_client


# ─────────────────────────────────────────────────────────────────────────────
# non_linear_state_machine / dispute_cycle_under_review_seller_responded_repeats
# ─────────────────────────────────────────────────────────────────────────────

def test_dispute_cycle_two_rounds_increments_response_round(api, reviewer_headers):
    """PRD §3.8: "The seller may then respond, which moves the status from
    `UNDER_REVIEW` to `SELLER_RESPONDED` and increments `response_round` by 1."
    PRD §3.8: "From `SELLER_RESPONDED`, a reviewer may request more information,
    moving the status back to `UNDER_REVIEW` — but only while `response_round` is
    below 3."

    Design: Difficulty/non_linear_state_machine/dispute_cycle_under_review_seller_responded_repeats
    """
    # Two full open-review/respond cycles → response_round == 2, status SELLER_RESPONDED.
    seller, order, dispute = dispute_cycled(rounds=2)
    assert dispute["dispute_status"] == "SELLER_RESPONDED"
    assert dispute["response_round"] == 2


def test_dispute_single_respond_round_one(api, reviewer_headers):
    """PRD §3.8: "A reviewer opens the claim for review, moving `dispute_status` from
    `FILED` to `UNDER_REVIEW`. The seller may then respond, which moves the status
    from `UNDER_REVIEW` to `SELLER_RESPONDED` and increments `response_round` by 1."

    Design: Difficulty/non_linear_state_machine/dispute_cycle_under_review_seller_responded_repeats
    """
    seller, order, dispute = dispute_cycled(rounds=1)
    assert dispute["dispute_status"] == "SELLER_RESPONDED"
    assert dispute["response_round"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# non_linear_state_machine / order_parallel_settlement_and_clawback_dimensions...
# ─────────────────────────────────────────────────────────────────────────────

def test_partial_refund_flips_clawback_but_settlement_stays_pending(api, finance_headers):
    """PRD §3.6: "The order's `clawback_status` moves from `NONE` to `REFUND_CLAWED`".
    PRD §3.5: "An order matures — its `settlement_status` flips from `PENDING` to
    `AVAILABLE` — only when its settlement is still `PENDING`, the current UTC time
    is at or after the order's `settled_at` plus the active schedule's
    `maturation_days`".

    Design: Difficulty/non_linear_state_machine/order_parallel_settlement_and_clawback_dimensions_evolve_independently
    """
    set_clock("2026-06-01T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=10000)
    refund = create_requested_refund(order["id"], refund_amount_cents=3000, reason="BUYER_REMORSE")
    apply_refund(refund["id"])
    refetched = validate_success(api.get_order(order["id"], finance_headers), 200)
    # clawback dimension advanced; settlement dimension unchanged (no clock advance).
    assert refetched["clawback_status"] == "REFUND_CLAWED"
    assert refetched["settlement_status"] == "PENDING"


def test_new_order_starts_with_both_dimensions_at_initial(api, finance_headers):
    """PRD §3.4: "Order creation posts an `ORDER_PROCEEDS` ledger entry for that net
    amount in `PENDING` hold state, sets `settlement_status` to `PENDING` with
    `clawback_status` `NONE`".

    Design: Difficulty/non_linear_state_machine/order_parallel_settlement_and_clawback_dimensions_evolve_independently
    """
    set_clock("2026-06-01T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=10000)
    assert order["settlement_status"] == "PENDING"
    assert order["clawback_status"] == "NONE"


# ─────────────────────────────────────────────────────────────────────────────
# Corner / state_machines
# ─────────────────────────────────────────────────────────────────────────────

def test_dispute_open_review_after_three_rounds_returns_round_exhausted(api, reviewer_headers):
    """PRD §3.8: "Once `response_round` has reached 3, the cycle is exhausted and a
    further open-review request is rejected with `ERR_DISPUTE_ROUND_EXHAUSTED`
    (HTTP 422)."

    Design: Corner/state_machines/dispute_open_review_after_three_rounds_returns_round_exhausted
    """
    seller, order, dispute = dispute_cycled(rounds=3)
    assert dispute["response_round"] == 3
    res = api.open_review_dispute(dispute["id"], reviewer_headers)
    validate_error(res, "ERR_DISPUTE_ROUND_EXHAUSTED", expected_status=422)


def test_dispute_granted_cascades_clawback_and_balance(api, reviewer_headers, finance_headers):
    """PRD §3.8: "From `UNDER_REVIEW`, an `outcome` for the buyer moves the dispute to
    `GRANTED`: the platform sets `granted_amount_cents` to the order's full
    `gross_amount_cents`, and if the order has not already been clawed, posts a
    negative full-gross `REFUND_CLAWBACK` ledger entry, drives the order's
    `clawback_status` from `NONE` to `REFUND_CLAWED`, and reconciles the seller's
    balances."

    Design: Corner/state_machines/dispute_granted_cascades_clawback_and_balance
    """
    seller, order, dispute = dispute_in_under_review(order_gross=9000)
    decided = validate_success(
        api.decide_dispute(dispute["id"], {"outcome": "GRANTED"}, reviewer_headers), 200
    )
    assert decided["dispute_status"] == "GRANTED"
    assert decided["granted_amount_cents"] == 9000
    refetched_order = validate_success(api.get_order(order["id"], finance_headers), 200)
    assert refetched_order["clawback_status"] == "REFUND_CLAWED"


def test_refund_apply_twice_idempotency_second_returns_invalid_state(api, finance_headers):
    """PRD §3.6: "Applying a refund ... requires that the refund is `REQUESTED`".
    PRD §3.6: "the refund's `refund_status` becomes `APPLIED`".
    PRD §2.11: "Then whether the target resource is in a state from which the
    requested transition is defined (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/refund_apply_twice_idempotency_second_returns_invalid_state
    """
    set_clock("2026-01-20T00:00:00Z")
    create_fee_schedule()
    seller = create_seller()
    order = create_order(seller["id"], gross_amount_cents=10000)
    refund = create_requested_refund(order["id"], refund_amount_cents=2000)
    applied = apply_refund(refund["id"])
    assert applied["refund_status"] == "APPLIED"
    res = api.apply_refund(refund["id"], finance_headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    refetched = validate_success(api.get_refund(refund["id"], finance_headers), 200)
    assert refetched["refund_status"] == "APPLIED"
