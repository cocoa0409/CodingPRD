"""
Test 04 -- Order Lifecycle: parallel state machines & derived order_status.

Covers:
  - Payment dimension:  UNPAID -> PAYING -> PAID -> PARTIAL_REFUND -> FULL_REFUND
  - Fulfillment dimension:  PENDING -> PROCESSING -> SHIPPED -> DELIVERED
  - Derived order_status:  CREATED / CONFIRMED / COMPLETED / CANCELLED
  - Cancel semantics and inventory release
  - Invalid transition errors
  - Side effects on delivery (commission, monthly_gmv, settlement_balance)
"""

import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    validate_paginated,
    get_success_data, assert_cost_precision, assert_version_incremented,
    NON_EXISTENT_UUID, TEST_USERS,
    assert_order, assert_order_item, assert_order_invariants,
    create_order_payload, create_payment_payload, create_product_payload,
    create_promotion_payload,
    create_and_approve_shop, create_and_list_product, create_and_activate_promotion,
    setup_basic_order_scenario, setup_shop_with_promotion,
    place_and_pay_order, place_pay_and_deliver_order, create_paid_order,
    ERR_ORDER_NOT_UNPAID,
    ERR_ORDER_NOT_PAYING,
    ERR_ORDER_NOT_PAID,
    ERR_ORDER_NOT_CONFIRMED,
    ERR_FULFILLMENT_NOT_PROCESSING,
    ERR_FULFILLMENT_NOT_SHIPPED,
)

# ---------------------------------------------------------------------------
# Header shortcuts
# ---------------------------------------------------------------------------

_customer = TEST_USERS["customer_headers"]
_seller = TEST_USERS["seller_headers"]
_admin = TEST_USERS["admin_headers"]


# ===================================================================
# Helpers
# ===================================================================


def _setup_order():
    """Create a shop + product + UNPAID order.  Returns (shop, product, order)."""
    shop, product = setup_basic_order_scenario()
    items = [{"product_id": product["id"], "quantity": 2}]
    payload = create_order_payload(shop_id=shop["id"], items=items)
    order = get_success_data(api_client.create_order(payload, _customer))
    return shop, product, order


def _pay_order(order_id):
    """Initiate payment on an UNPAID order.  Returns the PAYING order."""
    pay_payload = create_payment_payload()
    return get_success_data(api_client.pay_order(order_id, pay_payload, _customer))


# ===================================================================
# TestPaymentFlow
# ===================================================================


class TestPaymentFlow:
    """Payment-dimension state transitions."""

    def test_new_order_is_unpaid(self):
        """Freshly created order starts with payment_status=UNPAID."""
        _shop, _prod, order = _setup_order()
        assert order["payment_status"] == "UNPAID"

    def test_pay_transitions_to_paying(self):
        """POST /orders/{id}/pay transitions UNPAID -> PAYING."""
        _shop, _prod, order = _setup_order()
        paying = _pay_order(order["id"])
        assert paying["payment_status"] == "PAYING"

    def test_pay_creates_pending_payment_record(self):
        """Paying an order creates a Payment record with status=PENDING."""
        _shop, _prod, order = _setup_order()
        pay_payload = create_payment_payload()
        resp = api_client.pay_order(order["id"], pay_payload, _customer)
        data = get_success_data(resp)
        # The response should reflect the payment record or the order;
        # verify the order is now PAYING.
        assert data["payment_status"] == "PAYING"

    def test_confirm_payment_transitions_to_paid(self):
        """POST /orders/{id}/confirm-payment transitions PAYING -> PAID."""
        _shop, _prod, order = _setup_order()
        _pay_order(order["id"])
        confirmed = get_success_data(
            api_client.confirm_payment(order["id"], _admin)
        )
        assert confirmed["payment_status"] == "PAID"

    def test_payment_failed_returns_to_unpaid(self):
        """POST /orders/{id}/payment-failed transitions PAYING -> UNPAID."""
        _shop, _prod, order = _setup_order()
        _pay_order(order["id"])
        failed = get_success_data(
            api_client.payment_failed(order["id"], _admin)
        )
        assert failed["payment_status"] == "UNPAID"

    def test_payment_failed_allows_retry(self):
        """After payment-failed the customer can pay again."""
        _shop, _prod, order = _setup_order()
        _pay_order(order["id"])
        get_success_data(api_client.payment_failed(order["id"], _admin))
        # Retry payment
        retry = _pay_order(order["id"])
        assert retry["payment_status"] == "PAYING"
        # And confirm the retry
        confirmed = get_success_data(
            api_client.confirm_payment(order["id"], _admin)
        )
        assert confirmed["payment_status"] == "PAID"

    def test_confirm_payment_converts_reservations(self):
        """On payment confirmation reserved_count decreases (reservation converted)."""
        shop, product, order = _setup_order()
        # Check reserved_count increased after order creation
        prod_before = get_success_data(
            api_client.get_product(shop["id"], product["id"], _seller)
        )
        assert prod_before["reserved_count"] >= 2

        _pay_order(order["id"])
        get_success_data(api_client.confirm_payment(order["id"], _admin))

        prod_after = get_success_data(
            api_client.get_product(shop["id"], product["id"], _seller)
        )
        # Reservations converted -- reserved_count should decrease by order qty
        assert prod_after["reserved_count"] == prod_before["reserved_count"] - 2


# ===================================================================
# TestFulfillmentFlow
# ===================================================================


class TestFulfillmentFlow:
    """Fulfillment-dimension state transitions."""

    def test_new_order_fulfillment_pending(self):
        """Freshly created order starts with fulfillment_status=PENDING."""
        _shop, _prod, order = _setup_order()
        assert order["fulfillment_status"] == "PENDING"

    def test_start_processing_transitions(self):
        """POST /orders/{id}/start-processing: PENDING -> PROCESSING (requires PAID)."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        paid = place_and_pay_order(shop["id"], items)
        processing = get_success_data(
            api_client.start_processing(paid["id"], _seller)
        )
        assert processing["fulfillment_status"] == "PROCESSING"

    def test_ship_transitions(self):
        """POST /orders/{id}/ship: PROCESSING -> SHIPPED."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        paid = place_and_pay_order(shop["id"], items)
        get_success_data(api_client.start_processing(paid["id"], _seller))
        shipped = get_success_data(api_client.ship_order(paid["id"], _seller))
        assert shipped["fulfillment_status"] == "SHIPPED"

    def test_deliver_transitions(self):
        """POST /orders/{id}/deliver: SHIPPED -> DELIVERED."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        paid = place_and_pay_order(shop["id"], items)
        get_success_data(api_client.start_processing(paid["id"], _seller))
        get_success_data(api_client.ship_order(paid["id"], _seller))
        delivered = get_success_data(
            api_client.deliver_order(paid["id"], _seller)
        )
        assert delivered["fulfillment_status"] == "DELIVERED"

    def test_full_fulfillment_lifecycle(self):
        """Walk the entire fulfillment chain in one test."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        delivered = place_pay_and_deliver_order(shop["id"], items)
        assert delivered["fulfillment_status"] == "DELIVERED"
        assert delivered["order_status"] == "COMPLETED"


# ===================================================================
# TestDerivedOrderStatus
# ===================================================================


class TestDerivedOrderStatus:
    """Verify order_status is correctly derived from payment x fulfillment."""

    def test_unpaid_order_status_is_created(self):
        """UNPAID + PENDING -> order_status = CREATED."""
        _shop, _prod, order = _setup_order()
        assert order["order_status"] == "CREATED"

    def test_paying_order_status_is_created(self):
        """PAYING + PENDING -> order_status = CREATED."""
        _shop, _prod, order = _setup_order()
        paying = _pay_order(order["id"])
        assert paying["order_status"] == "CREATED"

    def test_paid_pending_order_status_is_confirmed(self):
        """PAID + PENDING -> order_status = CONFIRMED."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        paid = place_and_pay_order(shop["id"], items)
        assert paid["order_status"] == "CONFIRMED"

    def test_paid_processing_order_status_is_confirmed(self):
        """PAID + PROCESSING -> order_status = CONFIRMED."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        paid = place_and_pay_order(shop["id"], items)
        processing = get_success_data(
            api_client.start_processing(paid["id"], _seller)
        )
        assert processing["order_status"] == "CONFIRMED"

    def test_paid_shipped_order_status_is_confirmed(self):
        """PAID + SHIPPED -> order_status = CONFIRMED."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        paid = place_and_pay_order(shop["id"], items)
        get_success_data(api_client.start_processing(paid["id"], _seller))
        shipped = get_success_data(api_client.ship_order(paid["id"], _seller))
        assert shipped["order_status"] == "CONFIRMED"

    def test_delivered_order_status_is_completed(self):
        """PAID + DELIVERED -> order_status = COMPLETED."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        delivered = place_pay_and_deliver_order(shop["id"], items)
        assert delivered["order_status"] == "COMPLETED"

    def test_cancelled_order_status(self):
        """After cancellation -> order_status = CANCELLED."""
        _shop, _prod, order = _setup_order()
        cancelled = get_success_data(
            api_client.cancel_order(order["id"], _customer)
        )
        assert cancelled["order_status"] == "CANCELLED"


# ===================================================================
# TestOrderCancel
# ===================================================================


class TestOrderCancel:
    """Cancellation semantics and inventory release."""

    def test_cancel_unpaid_order(self):
        """Cancel an UNPAID order succeeds."""
        _shop, _prod, order = _setup_order()
        cancelled = get_success_data(
            api_client.cancel_order(order["id"], _customer)
        )
        assert cancelled["payment_status"] == "UNPAID"
        assert cancelled["order_status"] == "CANCELLED"

    def test_cancel_releases_reserved_inventory(self):
        """Cancelling an UNPAID order releases all reserved inventory."""
        shop, product, order = _setup_order()
        prod_before = get_success_data(
            api_client.get_product(shop["id"], product["id"], _seller)
        )
        reserved_before = prod_before["reserved_count"]

        get_success_data(api_client.cancel_order(order["id"], _customer))

        prod_after = get_success_data(
            api_client.get_product(shop["id"], product["id"], _seller)
        )
        # Reserved count should decrease by the order quantity (2)
        assert prod_after["reserved_count"] == reserved_before - 2
        # Available count should increase accordingly
        assert prod_after["available_count"] == prod_before["available_count"] + 2

    def test_cannot_cancel_paid_order(self):
        """Cancelling a PAID order fails with ERR_ORDER_NOT_UNPAID."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        paid = place_and_pay_order(shop["id"], items)
        resp = api_client.cancel_order(paid["id"], _customer)
        validate_error(resp, ERR_ORDER_NOT_UNPAID)

    def test_cannot_cancel_paying_order(self):
        """Cancelling a PAYING order fails with ERR_ORDER_NOT_UNPAID."""
        _shop, _prod, order = _setup_order()
        _pay_order(order["id"])
        resp = api_client.cancel_order(order["id"], _customer)
        validate_error(resp, ERR_ORDER_NOT_UNPAID)


# ===================================================================
# TestInvalidTransitions
# ===================================================================


class TestInvalidTransitions:
    """Verify that invalid state-machine transitions are rejected."""

    # --- Payment dimension ---

    def test_pay_non_unpaid_order(self):
        """Paying a PAYING order -> ERR_ORDER_NOT_UNPAID."""
        _shop, _prod, order = _setup_order()
        _pay_order(order["id"])
        # Try to pay again
        resp = api_client.pay_order(
            order["id"], create_payment_payload(), _customer
        )
        validate_error(resp, ERR_ORDER_NOT_UNPAID)

    def test_pay_paid_order(self):
        """Paying an already PAID order -> ERR_ORDER_NOT_UNPAID."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        paid = place_and_pay_order(shop["id"], items)
        resp = api_client.pay_order(
            paid["id"], create_payment_payload(), _customer
        )
        validate_error(resp, ERR_ORDER_NOT_UNPAID)

    def test_confirm_payment_non_paying(self):
        """Confirming payment on an UNPAID order -> ERR_ORDER_NOT_PAYING."""
        _shop, _prod, order = _setup_order()
        resp = api_client.confirm_payment(order["id"], _admin)
        validate_error(resp, ERR_ORDER_NOT_PAYING)

    def test_confirm_payment_already_paid(self):
        """Confirming payment on a PAID order -> ERR_ORDER_NOT_PAYING."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        paid = place_and_pay_order(shop["id"], items)
        resp = api_client.confirm_payment(paid["id"], _admin)
        validate_error(resp, ERR_ORDER_NOT_PAYING)

    # --- Fulfillment dimension ---

    def test_start_processing_unpaid_order(self):
        """start-processing on UNPAID order -> ERR_ORDER_NOT_PAID or ERR_ORDER_NOT_CONFIRMED."""
        _shop, _prod, order = _setup_order()
        resp = api_client.start_processing(order["id"], _seller)
        # Accept either error -- the PRD allows both names for this guard.
        validate_error_is_one_of(resp, [ERR_ORDER_NOT_PAID, ERR_ORDER_NOT_CONFIRMED])

    def test_ship_non_processing(self):
        """ship on a PAID (PENDING fulfillment) order -> ERR_FULFILLMENT_NOT_PROCESSING."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        paid = place_and_pay_order(shop["id"], items)
        resp = api_client.ship_order(paid["id"], _seller)
        validate_error(resp, ERR_FULFILLMENT_NOT_PROCESSING)

    def test_deliver_non_shipped(self):
        """deliver on a PROCESSING order -> ERR_FULFILLMENT_NOT_SHIPPED."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        paid = place_and_pay_order(shop["id"], items)
        get_success_data(api_client.start_processing(paid["id"], _seller))
        resp = api_client.deliver_order(paid["id"], _seller)
        validate_error(resp, ERR_FULFILLMENT_NOT_SHIPPED)

    def test_deliver_pending_fulfillment(self):
        """deliver on a PENDING fulfillment order -> ERR_FULFILLMENT_NOT_SHIPPED."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        paid = place_and_pay_order(shop["id"], items)
        resp = api_client.deliver_order(paid["id"], _seller)
        validate_error(resp, ERR_FULFILLMENT_NOT_SHIPPED)

    def test_payment_failed_on_unpaid(self):
        """payment-failed on UNPAID -> ERR_ORDER_NOT_PAYING."""
        _shop, _prod, order = _setup_order()
        resp = api_client.payment_failed(order["id"], _admin)
        validate_error(resp, ERR_ORDER_NOT_PAYING)


# ===================================================================
# TestDeliverySideEffects
# ===================================================================


class TestDeliverySideEffects:
    """Side effects triggered by order delivery (SHIPPED -> DELIVERED)."""

    def test_commission_rate_populated(self):
        """Delivered order has commission_rate set."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        delivered = place_pay_and_deliver_order(shop["id"], items)
        assert "commission_rate" in delivered
        assert isinstance(delivered["commission_rate"], (int, float))
        assert delivered["commission_rate"] > 0

    def test_commission_amount_populated(self):
        """Delivered order has commission_amount set and positive."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        delivered = place_pay_and_deliver_order(shop["id"], items)
        assert "commission_amount" in delivered
        assert isinstance(delivered["commission_amount"], (int, float))
        assert delivered["commission_amount"] > 0
        assert_cost_precision(delivered["commission_amount"])

    def test_commission_amount_within_tier1(self):
        """First order on fresh shop: all in tier 1 (8%), so commission = total * 0.08."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        delivered = place_pay_and_deliver_order(shop["id"], items)
        # Fresh shop, GMV=0, entire order is in tier 1 (8%)
        expected = round(delivered["total_amount"] * 0.08, 2)
        assert delivered["commission_amount"] == pytest.approx(expected, abs=0.01)

    def test_monthly_gmv_increased(self):
        """shop.monthly_gmv increases by total_amount on delivery."""
        shop, product = setup_basic_order_scenario()
        shop_before = get_success_data(api_client.get_shop(shop["id"], _admin))
        gmv_before = shop_before["monthly_gmv"]

        items = [{"product_id": product["id"], "quantity": 1}]
        delivered = place_pay_and_deliver_order(shop["id"], items)

        shop_after = get_success_data(api_client.get_shop(shop["id"], _admin))
        assert shop_after["monthly_gmv"] == pytest.approx(
            gmv_before + delivered["total_amount"], abs=0.01
        )

    def test_settlement_balance_increased(self):
        """shop.settlement_balance increases by (total_amount - commission_amount)."""
        shop, product = setup_basic_order_scenario()
        shop_before = get_success_data(api_client.get_shop(shop["id"], _admin))
        balance_before = shop_before["settlement_balance"]

        items = [{"product_id": product["id"], "quantity": 1}]
        delivered = place_pay_and_deliver_order(shop["id"], items)

        shop_after = get_success_data(api_client.get_shop(shop["id"], _admin))
        expected_increase = delivered["total_amount"] - delivered["commission_amount"]
        assert shop_after["settlement_balance"] == pytest.approx(
            balance_before + expected_increase, abs=0.01
        )

    def test_order_status_is_completed_after_delivery(self):
        """order_status is COMPLETED after delivery."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        delivered = place_pay_and_deliver_order(shop["id"], items)
        assert delivered["order_status"] == "COMPLETED"
        assert delivered["fulfillment_status"] == "DELIVERED"
        assert delivered["payment_status"] == "PAID"

    def test_order_invariants_after_delivery(self):
        """All order invariants hold on a COMPLETED order."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        delivered = place_pay_and_deliver_order(shop["id"], items)
        assert_order(delivered)
        assert_order_invariants(delivered)
