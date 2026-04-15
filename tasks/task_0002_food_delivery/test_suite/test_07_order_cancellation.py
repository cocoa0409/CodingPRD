"""Tests for order cancellation scenarios.

Covers: PRD Section 3.8 (Order Cancellation Scenarios), Table 2 (Order + payment_status transitions).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    setup_basic_order_scenario, confirm_order, prepare_order,
    mark_order_ready, create_and_approve_rider, assign_rider_to_order,
    create_active_customer, create_top_up_payload,
)


_admin = TEST_USERS["admin_headers"]
_restaurant = TEST_USERS["restaurant_headers"]
_customer = TEST_USERS["customer_headers"]
_rider = TEST_USERS["rider_headers"]


class TestCustomerCancellation:
    """PRD 3.8: Customer cancels own orders."""

    def test_cancel_placed_order(self):
        """PLACED -> CANCELLED_BY_CUSTOMER, payment_status stays PENDING, no charge."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        resp = api_client.cancel_order(order["id"], _customer)
        data = validate_success(resp)
        assert data["status"] == "CANCELLED_BY_CUSTOMER"
        assert data["payment_status"] == "PENDING"
        assert data["cancelled_at"] is not None

    def test_cancel_confirmed_order_no_delivery(self):
        """CONFIRMED -> CANCELLED_BY_CUSTOMER, payment AUTHORIZED -> REFUNDED, wallet restored."""
        rest, menu_items, customer, order = setup_basic_order_scenario(wallet_cents=100000)
        confirmed = confirm_order(order["id"])
        wallet_after_payment = 100000 - order["total_cents"]

        resp = api_client.cancel_order(order["id"], _customer)
        data = validate_success(resp)
        assert data["status"] == "CANCELLED_BY_CUSTOMER"
        assert data["payment_status"] == "REFUNDED"

        # Wallet should be restored
        c = get_success_data(api_client.get_customer(customer["id"], _admin))
        assert c["wallet_balance_cents"] == 100000, \
            f"Wallet should be restored to original after refund, got {c['wallet_balance_cents']}"

    def test_cancel_confirmed_order_with_assigned_delivery(self):
        """CONFIRMED -> CANCELLED_BY_CUSTOMER when delivery is ASSIGNED; delivery cancelled."""
        rest, menu_items, customer, order = setup_basic_order_scenario(wallet_cents=100000)
        confirm_order(order["id"])
        rider = create_and_approve_rider()
        delivery = assign_rider_to_order(order["id"], rider["id"])

        resp = api_client.cancel_order(order["id"], _customer)
        data = validate_success(resp)
        assert data["status"] == "CANCELLED_BY_CUSTOMER"
        assert data["payment_status"] == "REFUNDED"

        # Delivery should be cancelled
        d = get_success_data(api_client.get_delivery(order["id"], delivery["id"], _admin))
        assert d["status"] == "CANCELLED_BY_RIDER"

        # Rider active_delivery_count should decrease
        r = get_success_data(api_client.get_rider(rider["id"], _admin))
        assert r["active_delivery_count"] == 0

    def test_cannot_cancel_preparing_order(self):
        """ERR_CANCELLATION_TOO_LATE when order is PREPARING."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        confirm_order(order["id"])
        prepare_order(order["id"])
        resp = api_client.cancel_order(order["id"], _customer)
        validate_error(resp, ApiErrorId.ERR_CANCELLATION_TOO_LATE)

    def test_cannot_cancel_ready_for_pickup_order(self):
        """ERR_CANCELLATION_TOO_LATE when order is READY_FOR_PICKUP."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        confirm_order(order["id"])
        prepare_order(order["id"])
        mark_order_ready(order["id"])
        resp = api_client.cancel_order(order["id"], _customer)
        validate_error(resp, ApiErrorId.ERR_CANCELLATION_TOO_LATE)


class TestRestaurantRejection:
    """PRD 3.8: Restaurant rejects orders."""

    def test_reject_placed_order(self):
        """PLACED -> CANCELLED_BY_RESTAURANT, payment_status stays PENDING."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        resp = api_client.reject_order(order["id"], _restaurant)
        data = validate_success(resp)
        assert data["status"] == "CANCELLED_BY_RESTAURANT"
        assert data["payment_status"] == "PENDING"

    def test_reject_confirmed_order_triggers_refund(self):
        """CONFIRMED -> CANCELLED_BY_RESTAURANT, payment AUTHORIZED -> REFUNDED."""
        rest, menu_items, customer, order = setup_basic_order_scenario(wallet_cents=100000)
        confirm_order(order["id"])
        resp = api_client.reject_order(order["id"], _restaurant)
        data = validate_success(resp)
        assert data["status"] == "CANCELLED_BY_RESTAURANT"
        assert data["payment_status"] == "REFUNDED"

        # Customer wallet restored
        c = get_success_data(api_client.get_customer(customer["id"], _admin))
        assert c["wallet_balance_cents"] == 100000

    def test_cannot_reject_preparing_order(self):
        """Cannot reject once preparation has started."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        confirm_order(order["id"])
        prepare_order(order["id"])
        resp = api_client.reject_order(order["id"], _restaurant)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPlatformCancellation:
    """PRD 3.8: Platform admin cancels orders."""

    def test_platform_cancel_confirmed_order(self):
        """CONFIRMED -> CANCELLED_BY_PLATFORM with refund."""
        rest, menu_items, customer, order = setup_basic_order_scenario(wallet_cents=100000)
        confirm_order(order["id"])
        resp = api_client.platform_cancel_order(order["id"], _admin)
        data = validate_success(resp)
        assert data["status"] == "CANCELLED_BY_PLATFORM"
        assert data["payment_status"] == "REFUNDED"

    def test_platform_cancel_forbidden_for_customer(self):
        """Only platform_admin can platform-cancel."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        confirm_order(order["id"])
        resp = api_client.platform_cancel_order(order["id"], _customer)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
