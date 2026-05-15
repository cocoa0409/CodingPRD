"""Payment and logistics event ingress, parallel state dimensions
(PRD §3.4)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_money_invariant,
    cancel_force,
    capture_payment,
    confirm_order,
    deliver_order,
    dispatch_shipment,
    logistics_event_payload,
    make_customer_headers,
    payment_event_payload,
    reload_customer,
    reload_order,
    setup_subscription_with_order,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# PENDING → PAID
# ---------------------------------------------------------------------------
def test_payment_captured_moves_payment_status_to_paid(api):
    """PRD §3.4: 'A PAYMENT_CAPTURED event moves payment_status from
    PENDING to PAID, provided that fulfillment_status is in
    {SCHEDULED, CONFIRMED} (otherwise ERR_INVALID_ORDER_STATE).'
    """
    bundle = setup_subscription_with_order()
    order = bundle["order"]
    confirmed = confirm_order(bundle["customer"], order)
    paid = capture_payment(confirmed)
    assert paid["payment_status"] == "PAID"
    assert paid["fulfillment_status"] == "CONFIRMED"


def test_payment_captured_credits_customer_total_charged_cents(api):
    """PRD §3.4: '... and adds the order's total_cents to the
    customer's total_charged_cents.'

    PRD §2.10 money invariant: sum of PAID order total_cents must
    equal Customer.total_charged_cents.
    """
    bundle = setup_subscription_with_order()
    customer = bundle["customer"]
    order = bundle["order"]
    confirmed = confirm_order(customer, order)
    paid = capture_payment(confirmed)
    customer_after = reload_customer(customer["id"])
    assert customer_after["total_charged_cents"] == paid["total_cents"]
    assert customer_after["total_refunded_cents"] == 0
    assert_money_invariant(customer_after, paid["total_cents"], 0)


# ---------------------------------------------------------------------------
# PENDING → FAILED cascades fulfillment to CANCELLED
# ---------------------------------------------------------------------------
def test_payment_failed_cascades_fulfillment_to_cancelled(api):
    """PRD §3.4: 'A PAYMENT_FAILED event moves payment_status from
    PENDING to FAILED with no preconditions; if fulfillment_status is
    SCHEDULED or CONFIRMED at that moment, the fulfillment dimension
    cascades to CANCELLED as a side effect.'
    """
    bundle = setup_subscription_with_order()
    order = bundle["order"]
    res = api.post_payment_event(
        order["id"], payment_event_payload("PAYMENT_FAILED"),
        TEST_USERS["payment_adapter_headers"],
    )
    after = validate_success(res)
    assert after["payment_status"] == "FAILED"
    assert after["fulfillment_status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# PAID → REFUNDED requires fulfillment_status == CANCELLED
# ---------------------------------------------------------------------------
def test_payment_refunded_requires_fulfillment_cancelled(api):
    """PRD §3.4: 'A PAYMENT_REFUNDED event moves payment_status from
    PAID to REFUNDED, provided that fulfillment_status is already
    CANCELLED (otherwise ERR_INVALID_ORDER_STATE).'
    """
    bundle = setup_subscription_with_order()
    order = bundle["order"]
    confirmed = confirm_order(bundle["customer"], order)
    capture_payment(confirmed)
    # Try to refund while fulfillment is still CONFIRMED.
    res = api.post_payment_event(
        order["id"], payment_event_payload("PAYMENT_REFUNDED"),
        TEST_USERS["payment_adapter_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_ORDER_STATE.value)


def test_payment_refunded_after_cancel_credits_refunded_counter(api):
    """PRD §3.4: '... and adds the order's total_cents to the
    customer's total_refunded_cents.' PRD §2.10 money invariant.
    """
    bundle = setup_subscription_with_order()
    customer = bundle["customer"]
    sub = bundle["subscription"]
    order = bundle["order"]
    confirmed = confirm_order(customer, order)
    paid = capture_payment(confirmed)
    # Cancel the subscription with force → cascades order fulfillment
    # to CANCELLED while payment_status stays PAID.
    cancel_force(customer, sub, "OTHER")
    # Now refund.
    res = api.post_payment_event(
        order["id"], payment_event_payload("PAYMENT_REFUNDED"),
        TEST_USERS["payment_adapter_headers"],
    )
    after = validate_success(res)
    assert after["payment_status"] == "REFUNDED"
    assert after["fulfillment_status"] == "CANCELLED"
    customer_after = reload_customer(customer["id"])
    assert customer_after["total_refunded_cents"] == paid["total_cents"]


# ---------------------------------------------------------------------------
# CONFIRMED → SHIPPED requires payment_status == PAID
# ---------------------------------------------------------------------------
def test_shipment_dispatched_requires_paid(api):
    """PRD §3.4: 'A SHIPMENT_DISPATCHED event moves fulfillment_status
    from CONFIRMED to SHIPPED, provided that payment_status is PAID
    (otherwise ERR_INVALID_ORDER_STATE).'
    """
    bundle = setup_subscription_with_order()
    order = bundle["order"]
    confirmed = confirm_order(bundle["customer"], order)
    # payment_status is still PENDING.
    res = api.post_logistics_event(
        order["id"],
        logistics_event_payload(
            "SHIPMENT_DISPATCHED", tracking_number="TRK-001",
        ),
        TEST_USERS["logistics_adapter_headers"],
    )
    validate_error(res, ApiErrorId.ERR_INVALID_ORDER_STATE.value)


def test_shipment_dispatched_persists_tracking_number(api):
    """PRD §3.4: '... persists the supplied tracking_number on the
    order.'
    """
    bundle = setup_subscription_with_order()
    order = bundle["order"]
    confirmed = confirm_order(bundle["customer"], order)
    capture_payment(confirmed)
    shipped = dispatch_shipment(confirmed, "TRK-XYZ-99")
    assert shipped["tracking_number"] == "TRK-XYZ-99"
    assert shipped["fulfillment_status"] == "SHIPPED"


# ---------------------------------------------------------------------------
# SHIPPED → DELIVERED has no preconditions
# ---------------------------------------------------------------------------
def test_delivery_confirmed_moves_to_delivered(api):
    """PRD §3.4: 'A DELIVERY_CONFIRMED event moves fulfillment_status
    from SHIPPED to DELIVERED with no preconditions and opens the
    feedback collection window for that order.'
    """
    bundle = setup_subscription_with_order()
    order = bundle["order"]
    confirmed = confirm_order(bundle["customer"], order)
    capture_payment(confirmed)
    dispatch_shipment(confirmed)
    delivered = deliver_order(confirmed)
    assert delivered["fulfillment_status"] == "DELIVERED"


# ---------------------------------------------------------------------------
# Pause blocked when an order is in SHIPPED
# ---------------------------------------------------------------------------
def test_pause_blocked_when_order_in_transit(api):
    """PRD §3.2: 'with ERR_PAUSE_BLOCKED_IN_TRANSIT if any of the
    subscription's orders is currently in SHIPPED but not yet
    DELIVERED.'
    """
    from test_helpers import pause_subscription_payload

    bundle = setup_subscription_with_order()
    customer = bundle["customer"]
    sub = bundle["subscription"]
    order = bundle["order"]
    # Drive order to SHIPPED.
    confirmed = confirm_order(customer, order)
    capture_payment(confirmed)
    dispatch_shipment(confirmed)
    # Now try to pause.
    res = api.pause_subscription(
        sub["id"],
        pause_subscription_payload("2099-12-31T00:00:00.000Z"),
        make_customer_headers(customer["id"]),
    )
    validate_error(
        res, ApiErrorId.ERR_PAUSE_BLOCKED_IN_TRANSIT.value,
    )
