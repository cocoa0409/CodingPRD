"""Payments, store-credit application, and pickup gating; plus the fiscal/fabric
conservation invariants.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_fabric, create_master_tailor, create_open_room,
    create_ready_order, create_ready_order_balance_paid, create_confirmed_order,
    create_confirmed_order_with_deposit, create_picked_up_order,
    create_customer, create_profile,
    create_order_payload, create_option_line_payload, create_payment_payload,
    TEST_USERS, DEFAULT_DEPOSIT_CENTS,
)

SA = TEST_USERS["sales_associate_headers"]
FS = TEST_USERS["fitting_specialist_headers"]
SM = TEST_USERS["shop_manager_headers"]


# ─── Queue B: validations corner (overpayment) ──────────────────────────

def test_balance_overpayment_rejected(api):
    """PRD §3.4: "a `BALANCE` payment's `amount_cents` may not exceed the current `balance_due_cents` at all — the overpayment tolerance is zero cents — and a balance payment that would exceed the outstanding balance is rejected with `ERR_OVERPAYMENT_REJECTED` (HTTP 422)."

    READY order with balance_due 48750; paying BALANCE 48751 exceeds it by 1 cent.

    Design: Corner/validations/balance_overpayment_rejected
    """
    bundle = create_ready_order()  # default: locked 97500, deposit 48750 -> balance 48750
    order_id = bundle["order"]["id"]
    assert bundle["order"]["balance_due_cents"] == 48750
    res = api.create_payment(order_id, create_payment_payload("BALANCE", 48751), SA)
    validate_error(res, "ERR_OVERPAYMENT_REJECTED")


# ─── Queue B: endpoints corner (pickup blocked) ─────────────────────────

def test_pickup_blocked_by_outstanding_balance(api):
    """PRD §3.7: "A pickup may be recorded only on an order that is `READY` with a `balance_due_cents` of exactly 0; a pickup attempted while a balance remains outstanding is rejected with `ERR_BALANCE_OUTSTANDING` (HTTP 409)."

    READY order with the deposit paid but the balance unpaid (balance_due 48750) -> pickup
    rejected and the order stays READY.

    Design: Corner/endpoints/pickup_blocked_by_outstanding_balance
    """
    bundle = create_ready_order()
    order_id = bundle["order"]["id"]
    assert bundle["order"]["balance_due_cents"] == 48750
    res = api.pickup_order(order_id, {"released_to_name": "Bal Out"}, SA)
    validate_error(res, "ERR_BALANCE_OUTSTANDING")
    after = get_success_data(api.get_order(order_id, SA))
    assert after["status"] == "READY"


def test_pickup_succeeds_when_balance_settled(api):
    """PRD §3.7: "Recording a pickup takes a `released_to_name` for the person collecting the garment and stamps the system-set `picked_up_at` time; it advances the order from `READY` to `PICKED_UP`, increments the customer's `completed_order_count` by one".

    Companion to the blocked case: with the balance fully paid, pickup creates the Pickup
    (HTTP 201), advances the order to PICKED_UP, and bumps completed_order_count.

    Design: Corner/endpoints/pickup_blocked_by_outstanding_balance
    """
    bundle = create_ready_order_balance_paid()
    order_id = bundle["order"]["id"]
    customer_id = bundle["customer"]["id"]
    pickup = validate_success(api.pickup_order(order_id, {"released_to_name": "Happy Customer"}, SA), 201)
    assert pickup["released_to_name"] == "Happy Customer"
    after = get_success_data(api.get_order(order_id, SA))
    assert after["status"] == "PICKED_UP"
    customer = get_success_data(api.get_customer(customer_id, SA))
    assert customer["completed_order_count"] == 1


# ─── Queue B: endpoints corner (apply credit) ───────────────────────────

def test_apply_credit_reduces_balance_and_debits_customer(api):
    """PRD §3.4: "Applying credit debits the customer's `store_credit_cents` and adds the same amount to the order's `store_credit_applied_cents`, after which the balance is recomputed."
    PRD §3.4: "The order's `balance_due_cents` is the locked total minus the amount paid minus any store credit already applied (`store_credit_applied_cents`), floored at zero".

    A prior cancelled order refunds a 20750 deposit to store credit. The main READY order
    (balance 48750) applies 20750 -> balance 28000, store_credit_applied 20750,
    customer credit back to 0.

    Design: Corner/endpoints/apply_credit_reduces_balance_computed_read
    """
    # Shared customer across both orders so the credit accrues to them.
    customer = create_customer()
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=100)

    # Prior order: base 20000, 3.0m @ 8000, MONOGRAM -> locked 45500, deposit_due 22750.
    prof_prev = create_profile(customer["id"])
    prev = create_confirmed_order(customer=customer, profile=prof_prev, fabric=fabric,
                                  base_labor_cents=20000, fabric_meters_required=3.0,
                                  option_codes=("MONOGRAM",), bolt_meters_initial=100,
                                  garment_type="SHIRT")
    # Capture a 20750 deposit (allowed while CONFIRMED, amount > 0), then cancel -> refund.
    get_success_data(api.create_payment(prev["order"]["id"],
                                        create_payment_payload("DEPOSIT", 20750), SA))
    validate_success(api.cancel_order(prev["order"]["id"], SM), 200)
    seeded = get_success_data(api.get_customer(customer["id"], SA))
    assert seeded["store_credit_cents"] == 20750

    # Main order driven to READY (default shape: balance 48750).
    prof_main = create_profile(customer["id"])
    main = create_ready_order(customer=customer, profile=prof_main, fabric=fabric,
                              bolt_meters_initial=100, base_labor_cents=40000,
                              fabric_meters_required=7.0)
    order_id = main["order"]["id"]
    assert main["order"]["balance_due_cents"] == 48750

    updated = validate_success(api.apply_credit(order_id, {"amount_cents": 20750}, SA), 200)
    assert updated["balance_due_cents"] == 28000
    assert updated["store_credit_applied_cents"] == 20750
    customer_after = get_success_data(api.get_customer(customer["id"], SA))
    assert customer_after["store_credit_cents"] == 0


# ─── Queue A: compensating_invariant ────────────────────────────────────

def test_fabric_meters_conserved_confirm_then_cancel(api):
    """PRD §3.3: "the fabric's `bolt_meters_remaining` is reduced by the order's `fabric_meters_required` as a reservation".
    PRD §3.8: "each active fabric reservation it holds is released by crediting the order's `fabric_meters_required` back onto the fabric's `bolt_meters_remaining`, conserving the bolt's meters exactly."

    Confirm reserves 7 (50 -> 43); cancel releases 7 (back to 50). The conserved quantity
    bolt_meters_remaining returns to its pre-confirm value.

    Design: Difficulty/compensating_invariant/invariant_fabric_meters_conserved_on_confirm_then_cancel
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=50)
    bundle = create_confirmed_order(fabric=fabric, option_codes=("MONOGRAM",),
                                    bolt_meters_initial=50, base_labor_cents=40000,
                                    fabric_meters_required=7.0)
    fabric_id = bundle["fabric"]["id"]
    after_confirm = get_success_data(api.get_fabric(fabric_id, SM))
    assert after_confirm["bolt_meters_remaining"] == 43

    validate_success(api.cancel_order(bundle["order"]["id"], SM), 200)
    after_cancel = get_success_data(api.get_fabric(fabric_id, SM))
    assert after_cancel["bolt_meters_remaining"] == 50


def test_payment_cash_conserved_deposit_then_cancel_refund(api):
    """PRD §3.8: "Every `CAPTURED` payment on the order is set to `REFUNDED`, and the sum of those refunded amounts is added to the customer's `store_credit_cents` as a refund-to-credit, conserving the cash-equivalent."

    A 48750 deposit is captured; cancelling marks the payment REFUNDED and moves the full
    48750 into store credit — the cash-equivalent is conserved, neither created nor lost.

    Design: Difficulty/compensating_invariant/invariant_payment_cash_conserved_on_deposit_then_cancel_refund
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=50)
    bundle = create_confirmed_order_with_deposit(fabric=fabric, option_codes=("MONOGRAM", "CONTRAST_LINING"),
                                                 bolt_meters_initial=50, base_labor_cents=40000,
                                                 fabric_meters_required=7.0,
                                                 deposit_cents=DEFAULT_DEPOSIT_CENTS)
    order_id = bundle["order"]["id"]
    customer_id = bundle["customer"]["id"]
    payment_id = bundle["deposit_payment"]["id"]

    validate_success(api.cancel_order(order_id, SM), 200)

    payments = get_success_data(api.list_payments(order_id, SA))
    refunded = next(p for p in payments if p["id"] == payment_id)
    assert refunded["status"] == "REFUNDED"

    customer = get_success_data(api.get_customer(customer_id, SA))
    assert customer["store_credit_cents"] == 48750


def test_fabric_conserved_when_reserved_then_released_other_fabric_untouched(api):
    """PRD §3.3: "the fabric's `bolt_meters_remaining` is reduced by the order's `fabric_meters_required` as a reservation".
    PRD §3.8: "each active fabric reservation it holds is released by crediting the order's `fabric_meters_required` back onto the fabric's `bolt_meters_remaining`, conserving the bolt's meters exactly."

    Second invariant instance with a finer-grained meters figure (4.5m on a 30m bolt):
    confirm reserves 4.5 (30 -> 25.5) and cancel restores it exactly to 30.

    Design: Difficulty/compensating_invariant/invariant_fabric_meters_conserved_on_confirm_then_cancel
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=30)
    bundle = create_confirmed_order(fabric=fabric, option_codes=("MONOGRAM",),
                                    bolt_meters_initial=30, base_labor_cents=40000,
                                    fabric_meters_required=4.5)
    fabric_id = bundle["fabric"]["id"]
    after_confirm = get_success_data(api.get_fabric(fabric_id, SM))
    assert after_confirm["bolt_meters_remaining"] == 25.5

    validate_success(api.cancel_order(bundle["order"]["id"], SM), 200)
    after_cancel = get_success_data(api.get_fabric(fabric_id, SM))
    assert after_cancel["bolt_meters_remaining"] == 30


def test_payment_cash_conserved_credit_starts_at_zero(api):
    """PRD §3.8: "Every `CAPTURED` payment on the order is set to `REFUNDED`, and the sum of those refunded amounts is added to the customer's `store_credit_cents` as a refund-to-credit, conserving the cash-equivalent."
    PRD §3.1: "store_credit_cents` begins at 0".

    Second invariant instance: the customer's store credit starts at 0; after a 22750
    deposit is captured and the order cancelled, exactly 22750 lands in credit — no
    cash-equivalent is created or destroyed.

    Design: Difficulty/compensating_invariant/invariant_payment_cash_conserved_on_deposit_then_cancel_refund
    """
    fabric = create_fabric(price_per_meter_cents=8000, bolt_meters_initial=50)
    bundle = create_confirmed_order(fabric=fabric, option_codes=("MONOGRAM",),
                                    bolt_meters_initial=50, base_labor_cents=20000,
                                    fabric_meters_required=3.0, garment_type="SHIRT")
    order_id = bundle["order"]["id"]
    customer_id = bundle["customer"]["id"]
    before = get_success_data(api.get_customer(customer_id, SA))
    assert before["store_credit_cents"] == 0

    payment = get_success_data(api.create_payment(order_id, create_payment_payload("DEPOSIT", 22750), SA))
    validate_success(api.cancel_order(order_id, SM), 200)

    payments = get_success_data(api.list_payments(order_id, SA))
    refunded = next(p for p in payments if p["id"] == payment["id"])
    assert refunded["status"] == "REFUNDED"
    after = get_success_data(api.get_customer(customer_id, SA))
    assert after["store_credit_cents"] == 22750
