"""Cancellation cascades, refund settlement, and conserved-quantity invariants."""
from test_helpers import (
    validate_success,
    validate_paginated,
    make_customer_headers,
    make_dispatcher_headers,
    commit_payload,
)
import test_helpers.fixtures as fx


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade — cancel releases reservation, decrements capacity
# ---------------------------------------------------------------------------
def test_cancel_post_commit_releases_reservation_and_decrements_capacity(api):
    """PRD 3.13: "every `HELD` or `COMMITTED` slot reservation on the order is
    released to `RELEASED` (and a released *committed* reservation decrements the
    production day's `units_committed`, which may in turn unblock a buffer-adjacent
    production day)".
    PRD 3.13: "If it happens from `PROOF_APPROVED`, the late cancel forfeits the
    deposit portion - the refund is the captured amount minus `deposit_due_cents`,
    but never less than zero. The resulting refund amount is credited to the
    customer's `store_credit_cents`."

    Cancel of a paid-in-full PROOF_APPROVED order with a COMMITTED 2-unit PICKUP
    reservation: order CANCELLED, reservation RELEASED, units_committed back to 0,
    store credit = 20000 captured - 6000 deposit = 14000.

    Design: Difficulty/transitive_cascade/cancel_post_commit_releases_reservation_decrements_capacity
    """
    order, customer, reservation, product, pday = fx.setup_committed_pickup_order(units=2)
    headers = make_customer_headers(customer["id"])

    validate_success(api.cancel_order(order["id"], {"cancel_reason": "venue cancelled"}, headers), 200)

    order_after = validate_success(api.get_order(order["id"], headers), 200)
    assert order_after["production_status"] == "CANCELLED", order_after

    slots, _meta = validate_paginated(api.list_slots(order["id"], headers))
    assert any(s["id"] == reservation["id"] and s["status"] == "RELEASED" for s in slots), slots

    pday_after = validate_success(api.get_production_day(pday["id"], headers), 200)
    assert pday_after["units_committed"] == 0, pday_after

    cust_after = validate_success(api.get_customer(customer["id"], headers), 200)
    assert cust_after["store_credit_cents"] == 14000, cust_after


def test_cancel_post_commit_single_unit_releases_and_decrements(api):
    """PRD 3.13: "every `HELD` or `COMMITTED` slot reservation on the order is
    released to `RELEASED` (and a released *committed* reservation decrements the
    production day's `units_committed`, which may in turn unblock a buffer-adjacent
    production day)".

    A single-unit committed order (units_committed 1) cancelled from PROOF_APPROVED
    releases the reservation and returns units_committed to 0.

    Design: Difficulty/transitive_cascade/cancel_post_commit_releases_reservation_decrements_capacity
    """
    order, customer, reservation, product, pday = fx.setup_committed_pickup_order(units=1)
    headers = make_customer_headers(customer["id"])
    pday_mid = validate_success(api.get_production_day(pday["id"], headers), 200)
    assert pday_mid["units_committed"] == 1, pday_mid

    validate_success(api.cancel_order(order["id"], {"cancel_reason": "release me"}, headers), 200)
    slots, _meta = validate_paginated(api.list_slots(order["id"], headers))
    assert any(s["id"] == reservation["id"] and s["status"] == "RELEASED" for s in slots), slots
    pday_after = validate_success(api.get_production_day(pday["id"], headers), 200)
    assert pday_after["units_committed"] == 0, pday_after


# ---------------------------------------------------------------------------
# Queue A: dual_variant_calc / compensating_invariant — refund to store credit
# ---------------------------------------------------------------------------
def test_cancel_from_proof_pending_creates_refund_payment(api):
    """PRD 3.13: "When any capture is reversed, a `Payment` of `kind` `REFUND` is
    created and the payment status moves to `REFUNDED`."
    PRD 3.13: "If it happens from `PROOF_PENDING` or `CHANGES_REQUESTED`, the refund
    again equals the full captured amount: the deposit is returned in full."

    The full 6000 deposit refund surfaces as a REFUND Payment in the ledger.

    Design: Difficulty/dual_variant_calc/refund_credit_full_vs_deposit_forfeit
    """
    order, customer, proof, product, pday = fx.setup_proof_pending_order(units=2, image_ref="ref-pay")
    headers = make_customer_headers(customer["id"])
    validate_success(api.cancel_order(order["id"], {"cancel_reason": "refund payment"}, headers), 200)

    payments, _meta = validate_paginated(api.list_payments(order["id"], headers))
    refunds = [p for p in payments if p["kind"] == "REFUND"]
    assert len(refunds) == 1, payments
    assert refunds[0]["amount_cents"] == 6000, refunds


def test_cancel_from_proof_pending_refunds_full_deposit_to_credit(api):
    """PRD 3.13: "If it happens from `PROOF_PENDING` or `CHANGES_REQUESTED`, the
    refund again equals the full captured amount: the deposit is returned in full."
    PRD 3.13: "When any capture is reversed, a `Payment` of `kind` `REFUND` is
    created and the payment status moves to `REFUNDED`."

    A 6000 deposit captured then cancelled from PROOF_PENDING returns 6000 to
    store credit and the payment axis lands on REFUNDED.

    Design: Difficulty/dual_variant_calc/refund_credit_full_vs_deposit_forfeit
    """
    order, customer, proof, product, pday = fx.setup_proof_pending_order(units=2, image_ref="a-proof")
    headers = make_customer_headers(customer["id"])
    validate_success(api.cancel_order(order["id"], {"cancel_reason": "changed mind"}, headers), 200)

    cust_after = validate_success(api.get_customer(customer["id"], headers), 200)
    assert cust_after["store_credit_cents"] == 6000, cust_after

    order_after = validate_success(api.get_order(order["id"], headers), 200)
    assert order_after["payment_status"] == "REFUNDED", order_after
    assert order_after["production_status"] == "CANCELLED", order_after


def test_refund_conserves_money_via_store_credit(api):
    """PRD 3.13: "If it happens from `PROOF_PENDING` or `CHANGES_REQUESTED`, the
    refund again equals the full captured amount: the deposit is returned in full.
    ... The resulting refund amount is credited to the customer's
    `store_credit_cents`."

    The 6000 captured fresh tender reappears cent-for-cent as store credit; zero
    monetary drift.

    Design: Difficulty/compensating_invariant/refund_conserves_money_via_store_credit
    """
    order, customer, proof, product, pday = fx.setup_proof_pending_order(units=2, image_ref="p1")
    headers = make_customer_headers(customer["id"])
    cust_before = validate_success(api.get_customer(customer["id"], headers), 200)
    assert cust_before["store_credit_cents"] == 0, cust_before

    validate_success(api.cancel_order(order["id"], {"cancel_reason": "conserve money"}, headers), 200)
    cust_after = validate_success(api.get_customer(customer["id"], headers), 200)
    assert cust_after["store_credit_cents"] == 6000, cust_after
    order_after = validate_success(api.get_order(order["id"], headers), 200)
    assert order_after["payment_status"] == "REFUNDED", order_after


def test_refund_credit_equals_captured_via_refund_ledger(api):
    """PRD 3.13: "Let the captured amount be the sum of `amount_cents` over the
    order's captured non-refund payments (the deposit and balance legs; refund
    entries and the credit portion of a balance are excluded)."
    PRD 3.13: "When any capture is reversed, a `Payment` of `kind` `REFUND` is
    created and the payment status moves to `REFUNDED`."

    The captured 6000 deposit (the only non-refund payment) is exactly the amount
    that reappears as a REFUND ledger entry; money is conserved.

    Design: Difficulty/compensating_invariant/refund_conserves_money_via_store_credit
    """
    order, customer, proof, product, pday = fx.setup_proof_pending_order(units=2, image_ref="conserve2")
    headers = make_customer_headers(customer["id"])
    validate_success(api.cancel_order(order["id"], {"cancel_reason": "conserve ledger"}, headers), 200)

    payments, _meta = validate_paginated(api.list_payments(order["id"], headers))
    deposits = [p for p in payments if p["kind"] == "DEPOSIT"]
    refunds = [p for p in payments if p["kind"] == "REFUND"]
    assert len(deposits) == 1 and deposits[0]["amount_cents"] == 6000, payments
    assert len(refunds) == 1 and refunds[0]["amount_cents"] == 6000, payments


# ---------------------------------------------------------------------------
# Queue B: cross_cutting — deposit forfeit variant
# ---------------------------------------------------------------------------
def test_cancel_proof_approved_forfeits_deposit(api):
    """PRD 3.13: "If it happens from `PROOF_APPROVED`, the late cancel forfeits the
    deposit portion - the refund is the captured amount minus `deposit_due_cents`,
    but never less than zero. The resulting refund amount is credited to the
    customer's `store_credit_cents`."

    Fully paid (20000 captured, deposit 6000) at PROOF_APPROVED cancels with
    20000-6000=14000 routed to store credit; the deposit is forfeited.

    Design: Corner/cross_cutting_complexity_layers/cancel_proof_approved_forfeits_deposit
    """
    order, customer, proof, product, pday = fx.setup_paid_in_full_order(units=2)
    headers = make_customer_headers(customer["id"])
    validate_success(api.cancel_order(order["id"], {"cancel_reason": "late forfeit"}, headers), 200)

    cust_after = validate_success(api.get_customer(customer["id"], headers), 200)
    assert cust_after["store_credit_cents"] == 14000, cust_after
    order_after = validate_success(api.get_order(order["id"], headers), 200)
    assert order_after["payment_status"] == "REFUNDED", order_after
    assert order_after["production_status"] == "CANCELLED", order_after


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant — capacity conserved under commit+release
# ---------------------------------------------------------------------------
def test_capacity_conserved_under_commit_then_release(api):
    """PRD 3.11: "Releasing a reservation is the dispatcher's compensating action:
    it moves the reservation to `RELEASED` and increments the reservation's
    `version`, and if the reservation had been `COMMITTED`, it subtracts this
    order's units back out of the production day's `units_committed`".

    A 2-unit commit (units_committed -> 2) paired with its release returns
    units_committed to its pre-commit value of 0; zero drift.

    Design: Difficulty/compensating_invariant/capacity_conserved_under_commit_then_release
    """
    order, customer, reservation, product, pday = fx.setup_committed_pickup_order(units=2)
    dispatcher = make_dispatcher_headers()
    customer_headers = make_customer_headers(customer["id"])

    pday_committed = validate_success(api.get_production_day(pday["id"], customer_headers), 200)
    assert pday_committed["units_committed"] == 2, pday_committed

    released = validate_success(api.release_slot(order["id"], reservation["id"], {}, dispatcher), 200)
    assert released["status"] == "RELEASED", released

    pday_after = validate_success(api.get_production_day(pday["id"], customer_headers), 200)
    assert pday_after["units_committed"] == 0, pday_after


def test_released_capacity_can_be_recommitted_by_a_new_order(api):
    """PRD 3.11: "if the reservation had been `COMMITTED`, it subtracts this order's
    units back out of the production day's `units_committed`".
    PRD 3.11: "A reservation of the order's units is admissible exactly when the
    day's `units_committed` plus those units is at or below the effective capacity".

    On a cap-1 day, releasing the committed unit frees the tally so a fresh order
    commits successfully against the same day; capacity is conserved with no drift.

    Design: Difficulty/compensating_invariant/capacity_conserved_under_commit_then_release
    """
    order, customer, reservation, product, pday = fx.setup_committed_pickup_order(
        units=1, pday_overrides={"unit_capacity": 1})
    dispatcher = make_dispatcher_headers()
    customer_headers = make_customer_headers(customer["id"])
    validate_success(api.release_slot(order["id"], reservation["id"], {}, dispatcher), 200)

    second = fx.create_order(customer, product, pday)
    fx.add_line(second, customer, units=1)
    fx.quote(second, customer)
    fx.pay_deposit(second, customer)
    proof = fx.post_proof(second, "recommit")
    fx.approve_proof(second, proof, customer)
    fx.pay_balance(second, customer, 0)
    res2 = fx.create_slot(second, customer, "PICKUP")
    fresh = validate_success(api.get_order(second["id"], customer_headers), 200)
    committed = validate_success(
        api.commit_slot(second["id"], res2["id"], commit_payload(fresh["version"]), dispatcher), 200)
    assert committed["status"] == "COMMITTED", committed
    pday_after = validate_success(api.get_production_day(pday["id"], customer_headers), 200)
    assert pday_after["units_committed"] == 1, pday_after


def test_release_held_reservation_leaves_capacity_unchanged(api):
    """PRD 3.11: "a held reservation that was never committed consumed no units, so
    releasing it changes no tally".

    Design: Corner/endpoints/release_held_reservation_no_capacity_change
    """
    order, customer, proof, product, pday = fx.setup_proof_approved_order(units=2)
    customer_headers = make_customer_headers(customer["id"])
    reservation = fx.create_slot(order, customer, "PICKUP")  # HELD, never committed
    dispatcher = make_dispatcher_headers()

    released = validate_success(api.release_slot(order["id"], reservation["id"], {}, dispatcher), 200)
    assert released["status"] == "RELEASED", released

    pday_after = validate_success(api.get_production_day(pday["id"], customer_headers), 200)
    assert pday_after["units_committed"] == 0, pday_after
