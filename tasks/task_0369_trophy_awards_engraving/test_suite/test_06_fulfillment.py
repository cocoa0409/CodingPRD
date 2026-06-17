"""Fulfillment: ship-fee tiers, hand-off gating, on-time-rate recompute, payment mismatch (queue B)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    make_customer_headers,
    make_staff_headers,
    fixtures,
    factories,
)

STAFF = make_staff_headers()


def test_ship_fulfillment_branch_computes_fee(api):
    """PRD §3.8: "a parcel over 1000 grams and up to 5000 grams costs that 1200-cent base
    plus 300 cents for each additional whole kilogram above the first, where the number of
    additional kilograms is the grams above 1000 divided by 1000 and floored".

    Design: Corner/state_machines/ship_fulfillment_branch_computes_fee
    """
    ctx = fixtures.setup_ready_order(
        product_overrides={"base_price_cents": 10000, "standard_lead_days": 3},
        on_hand_qty=10, pay_full=True,
    )
    order = ctx["order"]
    resp = api.create_fulfillment(
        order["id"],
        factories.create_fulfillment_payload("SHIP", ship_address="1 Main St", ship_weight_grams=2000),
        STAFF,
    )
    data = validate_success(resp, 201)
    assert data["ship_fee_cents"] == 1500
    assert data["fulfillment_status"] == "STAGED"


def test_ship_fee_heavy_tier_over_5kg(api):
    """PRD §3.8: "a parcel over 5000 grams costs the 1200-cent base plus the four mid-tier
    kilogram charges of 300 cents each (1200 cents) plus 500 cents for each whole kilogram
    above 5000, where that heavy-kilogram count is the grams above 5000 divided by 1000 and
    floored."

    Design: Corner/calculations/ship_fee_heavy_tier_over_5kg
    """
    ctx = fixtures.setup_ready_order(
        product_overrides={"base_price_cents": 10000, "standard_lead_days": 3},
        on_hand_qty=10, pay_full=True,
    )
    order = ctx["order"]
    resp = api.create_fulfillment(
        order["id"],
        factories.create_fulfillment_payload("SHIP", ship_address="1 Main St", ship_weight_grams=7000),
        STAFF,
    )
    data = validate_success(resp, 201)
    assert data["ship_fee_cents"] == 3400


def test_ship_fulfillment_missing_weight_returns_ship_weight_required(api):
    """PRD §3.8: "For a `SHIP`, a `ship_address` must be present and `ship_weight_grams` must
    be greater than 0, or staging is rejected with `ERR_SHIP_WEIGHT_REQUIRED`, and the
    shipping fee is computed by weight at staging time."

    Design: Corner/validations/ship_fulfillment_missing_weight_returns_ship_weight_required
    """
    ctx = fixtures.setup_ready_order(
        product_overrides={"base_price_cents": 10000, "standard_lead_days": 3},
        on_hand_qty=10, pay_full=True,
    )
    order = ctx["order"]
    resp = api.create_fulfillment(
        order["id"], factories.create_fulfillment_payload("SHIP", ship_address="1 Main St"), STAFF
    )
    validate_error(resp, ApiErrorId.ERR_SHIP_WEIGHT_REQUIRED.value)


def test_hand_off_before_paid_in_full_returns_balance_due(api):
    """PRD §3.8: "Hand-off requires the fulfillment to be `STAGED`, the owning order to be in
    `READY`, and the order's `payment_status` to be `PAID_IN_FULL`; an order with a balance
    still owing is rejected with `ERR_BALANCE_DUE`."

    Design: Corner/validations/hand_off_before_paid_in_full_returns_balance_due
    """
    # READY order with only the deposit paid (pay_full=False) -> balance still owing.
    ctx = fixtures.setup_ready_order(
        product_overrides={"base_price_cents": 10000, "standard_lead_days": 3},
        on_hand_qty=10, pay_full=False,
    )
    order, cust_obj = ctx["order"], ctx["customer"]
    cust = make_customer_headers(cust_obj["id"])
    fulfillment = validate_success(
        api.create_fulfillment(order["id"], factories.create_fulfillment_payload("PICKUP"), STAFF), 201
    )
    resp = api.hand_off(order["id"], fulfillment["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_BALANCE_DUE.value)
    fulfillments, _meta = validate_paginated(api.list_fulfillments(order["id"], cust))
    assert fulfillments[0]["fulfillment_status"] == "STAGED"
    reread = validate_success(api.get_order(order["id"], cust))
    assert reread["production_status"] == "READY"


def test_payment_amount_mismatch_deposit(api):
    """PRD §3.6: "Its `amount_cents` must equal `deposit_due_cents` exactly, or the payment
    is rejected with `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/validations/payment_amount_mismatch_deposit
    """
    ctx = fixtures.setup_confirmed_order(
        product_overrides={"base_price_cents": 10000, "standard_lead_days": 3}, on_hand_qty=10
    )
    order, cust_obj = ctx["order"], ctx["customer"]
    cust = make_customer_headers(cust_obj["id"])
    # deposit_due is 5000; pay 4000.
    resp = api.create_payment(order["id"], factories.create_payment_payload(4000, "DEPOSIT"), cust)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value)
    reread = validate_success(api.get_order(order["id"], cust))
    assert reread["payment_status"] == "UNPAID"


def test_on_time_rate_100_then_recompute(api):
    """PRD §3.8: "Fulfillment also updates the customer's standing: the customer's
    `lifetime_completed_orders` increases by 1, and the customer's `on_time_rate_pct` is
    recomputed as the count of that customer's `FULFILLED` orders whose `due_date_met` is
    true, divided by the total count of that customer's `FULFILLED` orders, multiplied by
    100, and rounded half-up to two decimal places."
    PRD §3.8: "it stamps `fulfilled_at`, computes `due_date_met` as whether the calendar
    date of `fulfilled_at` is on or before the calendar date of `due_date`".

    Design: Corner/calculations/on_time_rate_100_then_recompute
    """
    # setup_fulfilled_order builds a PICKUP order handed off with clock at 2026-06-15 and
    # default due 2026-07-15 -> on time.
    ctx = fixtures.setup_fulfilled_order(
        product_overrides={"base_price_cents": 10000, "standard_lead_days": 3}, on_hand_qty=10
    )
    order, cust_obj = ctx["order"], ctx["customer"]
    cust = make_customer_headers(cust_obj["id"])
    assert order["production_status"] == "FULFILLED"
    assert order["due_date_met"] is True
    customer = validate_success(api.get_customer(cust_obj["id"], cust))
    assert customer["lifetime_completed_orders"] == 1
    assert customer["on_time_rate_pct"] == 100.0
