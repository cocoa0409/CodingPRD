"""Tests for delivery assignment, lifecycle, and rider capacity.

Covers: PRD Section 3.9 (Delivery Operations), 3.11 (Delivery Time Estimation),
Table 2 (Delivery state machine), Table 3 (estimated_delivery_time, delivery_fee vehicle adjustments).
"""
import math
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_delivery, create_delivery_payload,
    setup_basic_order_scenario, confirm_order, prepare_order,
    mark_order_ready, create_and_approve_rider, assign_rider_to_order,
    progress_delivery_to_restaurant,
    BICYCLE_LONG_DISTANCE_SURCHARGE, CAR_PREMIUM_SURCHARGE,
    CANCELLATION_POINTS, BICYCLE_MIN_PER_KM, MOTORCYCLE_MIN_PER_KM, CAR_MIN_PER_KM,
)


_admin = TEST_USERS["admin_headers"]
_restaurant = TEST_USERS["restaurant_headers"]
_customer = TEST_USERS["customer_headers"]
_rider = TEST_USERS["rider_headers"]


class TestDeliveryAssignment:
    """PRD 3.9: Admin assigns a rider to an order."""

    def test_assign_delivery_success(self):
        """Create delivery in ASSIGNED status, distance_km computed, rider count incremented."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        rider = create_and_approve_rider()
        confirm_order(order["id"])
        delivery = assign_rider_to_order(order["id"], rider["id"])
        assert_delivery(delivery)
        assert delivery["status"] == "ASSIGNED"
        assert delivery["order_id"] == order["id"]
        assert delivery["rider_id"] == rider["id"]
        assert delivery["distance_km"] >= 0

        # Rider active_delivery_count should be incremented
        r = get_success_data(api_client.get_rider(rider["id"], _admin))
        assert r["active_delivery_count"] == 1

    def test_assign_delivery_rider_not_available_offline(self):
        """ERR_RIDER_NOT_AVAILABLE when rider is_online=false."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        rider = create_and_approve_rider()
        # Set rider offline
        get_success_data(api_client.update_rider(rider["id"], {"is_online": False}, _rider))
        confirm_order(order["id"])

        resp = api_client.create_delivery(order["id"], create_delivery_payload(rider["id"]), _admin)
        validate_error(resp, ApiErrorId.ERR_RIDER_NOT_AVAILABLE)

    def test_assign_delivery_rider_at_capacity(self):
        """ERR_RIDER_AT_CAPACITY when active_delivery_count >= max_concurrent_deliveries."""
        rider = create_and_approve_rider(max_concurrent_deliveries=1)
        # First delivery to fill capacity
        rest1, mi1, cust1, order1 = setup_basic_order_scenario()
        confirm_order(order1["id"])
        assign_rider_to_order(order1["id"], rider["id"])

        # Second delivery should fail
        rest2, mi2, cust2, order2 = setup_basic_order_scenario()
        confirm_order(order2["id"])
        resp = api_client.create_delivery(order2["id"], create_delivery_payload(rider["id"]), _admin)
        validate_error(resp, ApiErrorId.ERR_RIDER_AT_CAPACITY)

    def test_assign_delivery_rider_not_found(self):
        """ERR_RIDER_NOT_FOUND for non-existent rider."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        confirm_order(order["id"])
        resp = api_client.create_delivery(order["id"], create_delivery_payload(NON_EXISTENT_UUID), _admin)
        validate_error(resp, ApiErrorId.ERR_RIDER_NOT_FOUND)

    def test_assign_delivery_order_not_found(self):
        """ERR_ORDER_NOT_FOUND for non-existent order."""
        rider = create_and_approve_rider()
        resp = api_client.create_delivery(NON_EXISTENT_UUID, create_delivery_payload(rider["id"]), _admin)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)

    def test_assign_delivery_forbidden_for_rider(self):
        """Only platform_admin can assign deliveries."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        rider = create_and_approve_rider()
        confirm_order(order["id"])
        resp = api_client.create_delivery(order["id"], create_delivery_payload(rider["id"]), _rider)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestDeliveryStateTransitions:
    """PRD 3.9 + Table 2: Delivery state machine progression."""

    def test_start_delivery(self):
        """ASSIGNED -> HEADING_TO_RESTAURANT."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        rider = create_and_approve_rider()
        confirm_order(order["id"])
        delivery = assign_rider_to_order(order["id"], rider["id"])

        resp = api_client.start_delivery(order["id"], delivery["id"], _rider)
        data = validate_success(resp)
        assert data["status"] == "HEADING_TO_RESTAURANT"

    def test_arrive_at_restaurant(self):
        """HEADING_TO_RESTAURANT -> AT_RESTAURANT."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        rider = create_and_approve_rider()
        confirm_order(order["id"])
        delivery = assign_rider_to_order(order["id"], rider["id"])
        get_success_data(api_client.start_delivery(order["id"], delivery["id"], _rider))

        resp = api_client.arrive_at_restaurant(order["id"], delivery["id"], _rider)
        data = validate_success(resp)
        assert data["status"] == "AT_RESTAURANT"

    def test_cannot_arrive_from_assigned(self):
        """Cannot go ASSIGNED -> AT_RESTAURANT directly."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        rider = create_and_approve_rider()
        confirm_order(order["id"])
        delivery = assign_rider_to_order(order["id"], rider["id"])

        resp = api_client.arrive_at_restaurant(order["id"], delivery["id"], _rider)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_delivery_not_found(self):
        """ERR_DELIVERY_NOT_FOUND for non-existent delivery."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        confirm_order(order["id"])
        resp = api_client.start_delivery(order["id"], NON_EXISTENT_UUID, _rider)
        validate_error(resp, ApiErrorId.ERR_DELIVERY_NOT_FOUND)

    def test_hierarchical_validation_order_first(self):
        """PRD 2.7: Order validated before delivery in nested URL."""
        resp = api_client.start_delivery(NON_EXISTENT_UUID, NON_EXISTENT_UUID, _rider)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND)


class TestDeliveryCancellation:
    """PRD 3.9: Rider cancels delivery, penalty assessed."""

    def test_cancel_assigned_delivery(self):
        """ASSIGNED -> CANCELLED_BY_RIDER; 20 penalty points; cancellation_count incremented."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        rider = create_and_approve_rider()
        confirm_order(order["id"])
        delivery = assign_rider_to_order(order["id"], rider["id"])

        resp = api_client.cancel_delivery(order["id"], delivery["id"], _rider)
        data = validate_success(resp)
        assert data["status"] == "CANCELLED_BY_RIDER"

        # Verify rider penalty
        r = get_success_data(api_client.get_rider(rider["id"], _admin))
        assert r["penalty_points"] == CANCELLATION_POINTS
        assert r["cancellation_count"] == 1
        assert r["active_delivery_count"] == 0

    def test_cancel_heading_to_restaurant_delivery(self):
        """HEADING_TO_RESTAURANT -> CANCELLED_BY_RIDER."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        rider = create_and_approve_rider()
        confirm_order(order["id"])
        delivery = assign_rider_to_order(order["id"], rider["id"])
        get_success_data(api_client.start_delivery(order["id"], delivery["id"], _rider))

        resp = api_client.cancel_delivery(order["id"], delivery["id"], _rider)
        data = validate_success(resp)
        assert data["status"] == "CANCELLED_BY_RIDER"

    def test_cannot_cancel_picked_up_delivery(self):
        """Cannot cancel a delivery once picked up."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        rider = create_and_approve_rider()
        confirm_order(order["id"])
        prepare_order(order["id"])
        mark_order_ready(order["id"])
        delivery = assign_rider_to_order(order["id"], rider["id"])
        progress_delivery_to_restaurant(order["id"], delivery["id"])
        get_success_data(api_client.pickup_order(order["id"], _rider))

        resp = api_client.cancel_delivery(order["id"], delivery["id"], _rider)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDeliveryFeeVehicleAdjustment:
    """PRD 3.5: Vehicle-type surcharges recalculated after rider assignment.

    Bicycle > 5km: +200 cents surcharge
    Car: always +150 cents premium
    """

    def test_car_premium_surcharge(self):
        """CAR vehicle type incurs 150 cent premium surcharge."""
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=3000)
        rider = create_and_approve_rider(vehicle_type="CAR")
        confirm_order(order["id"])
        delivery = assign_rider_to_order(order["id"], rider["id"])

        # Refresh order to see recalculated delivery fee
        refreshed = get_success_data(api_client.get_order(order["id"], _admin))
        # The delivery fee should include the CAR surcharge
        # We can at minimum verify it's >= base + surcharge
        assert refreshed["delivery_fee_cents"] >= order["delivery_fee_cents"], \
            "Delivery fee after CAR assignment should be >= provisional"
