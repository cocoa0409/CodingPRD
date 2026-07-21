"""Pre-order payment, fulfillment, cancellation cascade, and unit conservation.

Difficulty: transitive_cascade (cancel→promote), non_linear_state_machine (parallel
dimensions), compensating_invariant (unit conservation). Corner: state_machines,
validations, cross_cutting_complexity_layers.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_product_stock, assert_stock_conservation, TEST_USERS,
    create_member, setup_released_pool, setup_embargoed_pool,
    setup_allocated_preorder, setup_waitlisted_preorder,
    setup_allocated_paid_fulfilled_preorder,
    place_pre_order, pay_pre_order,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ─── Difficulty: cancel_allocated_preorder_promotes_waitlisted ────────────
def test_cancel_allocated_promotes_waitlisted_holder(api):
    """PRD §3.5: "if it is ALLOCATED, cancelling runs a three-hop cascade: hop 1 releases
    the held unit ... hop 2 runs the waitlist promotion selector over the freed pool; and
    hop 3, if a promotion winner exists, grants the freed unit to that winner. The
    promotion advances the winning pre-order WAITLISTED → ALLOCATED."

    Design: Difficulty/transitive_cascade/cancel_allocated_preorder_promotes_waitlisted
    """
    member_a = create_member(full_name="Alice")
    member_b = create_member(full_name="Bob")
    product, stock = setup_released_pool(unit_price_cents=7000, deposit_cents=2000, total_count=1)
    po_a = place_pre_order(member_a["id"], stock["id"])
    po_b = place_pre_order(member_b["id"], stock["id"])
    assert po_b["allocation_status"] == "WAITLISTED"

    cancelled = validate_success(api.cancel_pre_order(po_a["id"], CLERK), 200)
    assert cancelled["allocation_status"] == "RELEASED"

    po_b_after = validate_success(api.get_pre_order(po_b["id"], CLERK), 200)
    assert po_b_after["allocation_status"] == "ALLOCATED"


def test_cancel_allocated_conserves_pool_counts_through_promotion(api):
    """PRD §3.5: "so the net effect on the pool's counts is that the freed unit hops from
    the cancelled holder to the promoted waitlister."
    PRD §2.9: "the conservation invariant available_count + allocated_count +
    fulfilled_count equal to total_count holds at all times."

    Design: Difficulty/transitive_cascade/cancel_allocated_preorder_promotes_waitlisted
    """
    member_a = create_member(full_name="Alice")
    member_b = create_member(full_name="Bob")
    product, stock = setup_released_pool(unit_price_cents=7000, deposit_cents=2000, total_count=1)
    po_a = place_pre_order(member_a["id"], stock["id"])
    place_pre_order(member_b["id"], stock["id"])

    api.cancel_pre_order(po_a["id"], CLERK)
    fresh = validate_success(api.get_product_stock(stock["id"], CLERK), 200)
    assert fresh["available_count"] == 0
    assert fresh["allocated_count"] == 1
    assert fresh["fulfilled_count"] == 0
    assert_stock_conservation(fresh)


# ─── Difficulty: parallel payment/allocation dimensions ───────────────────
def test_waitlisted_preorder_can_advance_payment_to_deposit(api):
    """PRD §3.4: "Otherwise, if cumulative payment is at least deposit_cents but still
    below unit_price_cents, the status advances from UNPAID to DEPOSIT_PAID."
    PRD §3.3: "Every pre-order carries two independent status dimensions."

    Design: Difficulty/non_linear_state_machine/preorder_payment_and_allocation_dimensions_evolve_independently
    """
    member, product, stock, po = setup_waitlisted_preorder(
        unit_price_cents=6000, deposit_cents=2000, total_count=2)
    assert po["allocation_status"] == "WAITLISTED"

    paid = pay_pre_order(po["id"], 2000)
    assert paid["payment_status"] == "DEPOSIT_PAID"
    assert paid["allocation_status"] == "WAITLISTED"


def test_deposit_payment_records_amount_without_allocating(api):
    """PRD §3.4: "the amount is added to the running amount_paid_cents, which is never
    allowed to exceed the pool's unit_price_cents."
    PRD §3.3: "The payment dimension, payment_status (Section 3.4), is tracked separately."

    Design: Difficulty/non_linear_state_machine/preorder_payment_and_allocation_dimensions_evolve_independently
    """
    member, product, stock, po = setup_waitlisted_preorder(
        unit_price_cents=6000, deposit_cents=2000, total_count=2)
    paid = pay_pre_order(po["id"], 2000)
    assert paid["amount_paid_cents"] == 2000
    assert paid["allocation_status"] == "WAITLISTED"


# ─── Difficulty: stock_units_conserved_across_allocate_then_cancel ─────────
def test_allocate_then_cancel_restores_available_count(api):
    """PRD §2.9: "releasing an allocation on cancellation decrements allocated_count by
    one and increments available_count by one."
    PRD §3.5: "hop 1 releases the held unit — the owning Allocation moves HELD → RELEASED,
    the pool's allocated_count is decremented by one and its available_count incremented
    by one, and the pre-order's allocation_status becomes RELEASED."

    Design: Difficulty/compensating_invariant/stock_units_conserved_across_allocate_then_cancel
    """
    member, product, stock, po = setup_allocated_preorder(
        unit_price_cents=5000, deposit_cents=1000, total_count=1)
    api.cancel_pre_order(po["id"], CLERK)
    fresh = validate_success(api.get_product_stock(stock["id"], CLERK), 200)
    assert fresh["available_count"] == 1
    assert fresh["allocated_count"] == 0
    assert fresh["fulfilled_count"] == 0


def test_allocate_then_cancel_preserves_total_and_releases_preorder(api):
    """PRD §2.9: "The total is set at creation and never changes thereafter."
    PRD §3.5: "If it is ALLOCATED, cancelling runs a three-hop cascade ... and the
    pre-order's allocation_status becomes RELEASED."

    Design: Difficulty/compensating_invariant/stock_units_conserved_across_allocate_then_cancel
    """
    member, product, stock, po = setup_allocated_preorder(
        unit_price_cents=5000, deposit_cents=1000, total_count=1)
    cancelled = validate_success(api.cancel_pre_order(po["id"], CLERK), 200)
    assert cancelled["allocation_status"] == "RELEASED"
    fresh = validate_success(api.get_product_stock(stock["id"], CLERK), 200)
    assert fresh["total_count"] == 1
    assert_stock_conservation(fresh)


# ─── Corner: state_machines / cancel a FULFILLED pre-order ────────────────
def test_cancel_fulfilled_preorder_rejected(api):
    """PRD §3.5: "On success the allocation dimension advances ALLOCATED → FULFILLED."
    PRD §2.11: "then the target resource being in a legal state for the requested
    transition (ERR_INVALID_STATE, 409)."

    Design: Corner/state_machines/cancel_fulfilled_preorder_rejected
    """
    member, product, stock, po = setup_allocated_paid_fulfilled_preorder()
    assert po["allocation_status"] == "FULFILLED"
    res = api.cancel_pre_order(po["id"], CLERK)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Corner: validations / fulfill allocated-but-unpaid ───────────────────
def test_fulfill_allocated_unpaid_rejected(api):
    """PRD §3.5: "Fulfillment requires allocation_status equal to ALLOCATED and
    payment_status equal to PAID_IN_FULL; if either is not met, the request is rejected
    with ERR_ALLOCATION_NOT_READY (HTTP 409)."

    Design: Corner/validations/fulfill_allocated_but_unpaid_returns_409
    """
    member, product, stock, po = setup_allocated_preorder(
        unit_price_cents=6000, deposit_cents=2000, total_count=1)
    assert po["payment_status"] == "UNPAID"
    res = api.fulfill_pre_order(po["id"], CLERK)
    validate_error(res, "ERR_ALLOCATION_NOT_READY", expected_status=409)


# ─── Corner: validations / first payment below deposit ────────────────────
def test_first_payment_below_deposit_rejected(api):
    """PRD §3.4: "Each payment must be positive, the first payment must bring
    amount_paid_cents to at least the pool's deposit_cents, and no payment may push the
    cumulative amount_paid_cents above unit_price_cents; a violation of any of these is
    rejected with ERR_INSUFFICIENT_PAYMENT (HTTP 402)."

    Design: Corner/validations/preorder_first_payment_below_deposit_returns_402
    """
    member, product, stock, po = setup_waitlisted_preorder(
        unit_price_cents=6000, deposit_cents=2000, total_count=2)
    res = api.pay_pre_order(po["id"], {"amount_cents": 500}, CLERK)
    validate_error(res, "ERR_INSUFFICIENT_PAYMENT", expected_status=402)


# ─── Corner: cross_cutting / refund credited on cancel after deposit ──────
def test_cancel_after_deposit_credits_refund(api):
    """PRD §3.5: "Regardless of prior payment, cancelling moves payment_status to
    REFUNDED. If the pre-order had amount_paid_cents greater than zero ... the refund is
    issued as store credit: a StoreCreditEntry with reason PREORDER_REFUND and an
    amount_cents equal to the full paid amount is appended, and the member's
    store_credit_balance_cents is recomputed."

    Design: Corner/cross_cutting_complexity_layers/preorder_refund_credited_on_cancel_after_deposit
    """
    member, product, stock, po = setup_waitlisted_preorder(
        unit_price_cents=6000, deposit_cents=2000, total_count=2)
    pay_pre_order(po["id"], 2000)
    cancelled = validate_success(api.cancel_pre_order(po["id"], CLERK), 200)
    assert cancelled["payment_status"] == "REFUNDED"

    fetched = validate_success(api.get_member(member["id"], CLERK), 200)
    assert fetched["store_credit_balance_cents"] == 2000
