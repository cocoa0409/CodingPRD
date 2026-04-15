"""Tests for order fulfillment lifecycle and state transitions.

Covers: PRD Section 3.6 (Order Fulfillment Lifecycle), 3.7 (Commission and Payouts),
Table 2 (Order + payment_status state machines), Table 3 (commission_and_payouts, loyalty_points).
"""
import math
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_order, assert_delivery,
    setup_basic_order_scenario, confirm_order, prepare_order,
    mark_order_ready, create_and_approve_rider, assign_rider_to_order,
    progress_delivery_to_restaurant, pickup_and_deliver,
    complete_order_lifecycle, create_confirmed_order_with_delivery,
    create_active_customer, create_top_up_payload,
    RIDER_PLATFORM_FEE_RATE,
)


_admin = TEST_USERS["admin_headers"]
_restaurant = TEST_USERS["restaurant_headers"]
_customer = TEST_USERS["customer_headers"]
_rider = TEST_USERS["rider_headers"]


class TestOrderConfirmation:
    """PRD 3.6: Restaurant confirms a PLACED order."""

    def test_confirm_order_success(self):
        """PLACED -> CONFIRMED, payment_status PENDING -> AUTHORIZED, wallet debited."""
        rest, menu_items, customer, order = setup_basic_order_scenario(
            wallet_cents=100000, item_price_cents=2000
        )
        resp = api_client.confirm_order(order["id"], _restaurant)
        data = validate_success(resp)
        assert data["status"] == "CONFIRMED"
        assert data["payment_status"] == "AUTHORIZED"
        assert data["confirmed_at"] is not None

        # Customer wallet should be debited
        c = get_success_data(api_client.get_customer(customer["id"], _admin))
        assert c["wallet_balance_cents"] == 100000 - order["total_cents"], \
            f"Wallet should be debited by total_cents={order['total_cents']}"

    def test_confirm_insufficient_balance(self):
        """ERR_INSUFFICIENT_BALANCE when wallet cannot cover total_cents."""
        rest, menu_items, customer, order = setup_basic_order_scenario(
            wallet_cents=1, item_price_cents=2000
        )
        resp = api_client.confirm_order(order["id"], _restaurant)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_BALANCE)

    def test_confirm_non_placed_order(self):
        """Cannot confirm an already CONFIRMED order."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        confirm_order(order["id"])
        resp = api_client.confirm_order(order["id"], _restaurant)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_confirm_sets_estimated_prep_time(self):
        """Confirmation computes estimated_prep_time_minutes from max item prep times."""
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=2000)
        confirmed = confirm_order(order["id"])
        assert confirmed["estimated_prep_time_minutes"] is not None
        assert isinstance(confirmed["estimated_prep_time_minutes"], int)


class TestOrderPreparation:
    """PRD 3.6: CONFIRMED -> PREPARING -> READY_FOR_PICKUP."""

    def test_start_preparing(self):
        """CONFIRMED -> PREPARING."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        confirm_order(order["id"])
        resp = api_client.start_preparing_order(order["id"], _restaurant)
        data = validate_success(resp)
        assert data["status"] == "PREPARING"

    def test_mark_ready(self):
        """PREPARING -> READY_FOR_PICKUP."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        confirm_order(order["id"])
        prepare_order(order["id"])
        resp = api_client.mark_order_ready(order["id"], _restaurant)
        data = validate_success(resp)
        assert data["status"] == "READY_FOR_PICKUP"

    def test_cannot_start_preparing_from_placed(self):
        """Cannot start preparing from PLACED (must be CONFIRMED first)."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        resp = api_client.start_preparing_order(order["id"], _restaurant)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cannot_mark_ready_from_confirmed(self):
        """Cannot mark ready from CONFIRMED (must be PREPARING first)."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        confirm_order(order["id"])
        resp = api_client.mark_order_ready(order["id"], _restaurant)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestOrderPickupAndDelivery:
    """PRD 3.6: Pickup and delivery completion."""

    def test_pickup_order(self):
        """READY_FOR_PICKUP -> PICKED_UP; delivery status also updates."""
        rest, customer, rider, order, delivery = create_confirmed_order_with_delivery()
        resp = api_client.pickup_order(order["id"], _rider)
        data = validate_success(resp)
        assert data["status"] == "PICKED_UP"
        assert data["picked_up_at"] is not None

    def test_deliver_order(self):
        """PICKED_UP -> DELIVERED; payment AUTHORIZED -> CAPTURED; payouts credited."""
        rest, menu_items, customer, rider, order, delivery = complete_order_lifecycle(
            item_price_cents=3000, tip_cents=200, commission_rate=0.15
        )
        assert order["status"] == "DELIVERED"
        assert order["payment_status"] == "CAPTURED"
        assert order["delivered_at"] is not None

    def test_delivery_credits_restaurant_payout(self):
        """Restaurant balance_pending_cents increases by restaurant_payout_cents on delivery."""
        rest, menu_items, customer, rider, order, delivery = complete_order_lifecycle(
            item_price_cents=3000, commission_rate=0.15
        )
        # commission = floor(subtotal * 0.15)
        subtotal = order["subtotal_cents"]
        commission = math.floor(subtotal * 0.15)
        expected_payout = subtotal - commission
        assert order["restaurant_payout_cents"] == expected_payout

        refreshed_rest = get_success_data(api_client.get_restaurant(rest["id"], _admin))
        assert refreshed_rest["balance_pending_cents"] >= expected_payout

    def test_delivery_credits_rider_earnings(self):
        """Rider earnings_balance_cents increases by rider_payout_cents on delivery."""
        rest, menu_items, customer, rider, order, delivery = complete_order_lifecycle(
            item_price_cents=3000, tip_cents=300
        )
        # rider_platform_fee = floor(delivery_fee * 0.20)
        # rider_payout = delivery_fee - rider_platform_fee + tip
        delivery_fee = order["delivery_fee_cents"]
        platform_fee = math.floor(delivery_fee * RIDER_PLATFORM_FEE_RATE)
        expected_rider_payout = delivery_fee - platform_fee + 300
        assert order["rider_payout_cents"] == expected_rider_payout

        refreshed_rider = get_success_data(api_client.get_rider(rider["id"], _admin))
        assert refreshed_rider["earnings_balance_cents"] >= expected_rider_payout

    def test_delivery_increments_counters(self):
        """total_deliveries_completed, total_orders_completed, total_orders increment."""
        rest, menu_items, customer, rider, order, delivery = complete_order_lifecycle()
        r_rest = get_success_data(api_client.get_restaurant(rest["id"], _admin))
        assert r_rest["total_orders_completed"] >= 1

        r_rider = get_success_data(api_client.get_rider(rider["id"], _admin))
        assert r_rider["total_deliveries_completed"] >= 1

        r_cust = get_success_data(api_client.get_customer(customer["id"], _admin))
        assert r_cust["total_orders"] >= 1

    def test_delivery_awards_loyalty_points(self):
        """Customer earns floor(total_cents / 100) loyalty points (PRD 2.9, 3.6)."""
        rest, menu_items, customer, rider, order, delivery = complete_order_lifecycle(
            item_price_cents=5000
        )
        expected_points = math.floor(order["total_cents"] / 100)
        c = get_success_data(api_client.get_customer(customer["id"], _admin))
        assert c["loyalty_points"] >= expected_points


class TestCommissionCalculation:
    """PRD 3.7: Commission and payout formulas.

    Table 3 (commission_and_payouts):
    commission_amount_cents = floor(subtotal * commission_rate)
    restaurant_payout_cents = subtotal - commission
    rider_platform_fee = floor(delivery_fee * 0.20)
    rider_payout = delivery_fee - rider_platform_fee + tip
    """

    def test_commission_amount_floor(self):
        """commission_amount_cents = floor(subtotal * rate)."""
        # subtotal=3333, rate=0.15 -> floor(3333*0.15) = floor(499.95) = 499
        rest, menu_items, customer, rider, order, delivery = complete_order_lifecycle(
            item_price_cents=3333, commission_rate=0.15
        )
        expected_commission = math.floor(3333 * 0.15)  # 499
        assert order["commission_amount_cents"] == expected_commission, \
            f"Expected commission={expected_commission}, got {order['commission_amount_cents']}"

    def test_restaurant_payout_equals_subtotal_minus_commission(self):
        """restaurant_payout_cents = subtotal - commission."""
        rest, menu_items, customer, rider, order, delivery = complete_order_lifecycle(
            item_price_cents=4000, commission_rate=0.20
        )
        commission = math.floor(4000 * 0.20)  # 800
        expected_payout = 4000 - commission  # 3200
        assert order["restaurant_payout_cents"] == expected_payout

    def test_rider_platform_fee_floor(self):
        """rider_platform_fee = floor(delivery_fee * 0.20)."""
        rest, menu_items, customer, rider, order, delivery = complete_order_lifecycle(
            item_price_cents=3000, tip_cents=500
        )
        delivery_fee = order["delivery_fee_cents"]
        platform_fee = math.floor(delivery_fee * 0.20)
        expected_rider_payout = delivery_fee - platform_fee + 500
        assert order["rider_payout_cents"] == expected_rider_payout


class TestOrderNotFound:
    """Table 6: ERR_ORDER_NOT_FOUND."""

    def test_get_order_not_found(self):
        resp = api_client.get_order(NON_EXISTENT_UUID, _admin)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)

    def test_confirm_order_not_found(self):
        resp = api_client.confirm_order(NON_EXISTENT_UUID, _restaurant)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)
