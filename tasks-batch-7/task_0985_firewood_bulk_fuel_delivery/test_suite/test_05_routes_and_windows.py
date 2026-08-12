"""Delivery windows: capacity hierarchy, half-open overlap, lock gating (PRD §3.4)."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_delivery_window_payload, set_clock, create_customer,
    create_product, create_route, create_window, create_order,
    setup_catalog_with_route, submit_and_pay, schedule_order,
    create_payment_payload, TEST_USERS,
)

CS = TEST_USERS["customer_service_headers"]
OM = TEST_USERS["operations_manager_headers"]
RP = TEST_USERS["route_planner_headers"]


class TestWindowCapacityHierarchy:
    def test_window_capacity_mismatch_with_route(self, api):
        """PRD §3.4: "A window's capacity may not exceed its parent route's
        capacity, or the create is rejected with `ERR_CAPACITY_MISMATCH`."

        Design: Corner/validations/window_capacity_mismatch_with_route
        """
        set_clock()
        route = create_route(route_code="RCM", prefixes=("0",), capacity=5.0)
        res = api.create_delivery_window(create_delivery_window_payload(
            route["id"], service_date="2026-09-01", start_hour=8, end_hour=12,
            capacity_cord_equivalent=6.0), RP)
        validate_error(res, "ERR_CAPACITY_MISMATCH", expected_status=422)


class TestWindowHalfOpenOverlap:
    def _setup(self, api):
        set_clock()
        route = create_route(route_code="R16", prefixes=("1",), capacity=100.0)
        window_a = create_window(route["id"], service_date="2026-09-10",
                                 start_hour=8, end_hour=12, capacity=50.0)
        return route, window_a

    def test_delivery_window_adjacent_half_open_permitted(self, api):
        """PRD §3.4: "Two windows on the same route and date may not overlap;
        intervals are half-open, so adjacent windows where one ends exactly when
        the other begins are permitted, while a true overlap is rejected with
        `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/delivery_window_half_open_interval_overlap
        """
        route, _window_a = self._setup(api)
        res = api.create_delivery_window(create_delivery_window_payload(
            route["id"], service_date="2026-09-10", start_hour=12, end_hour=16,
            capacity_cord_equivalent=50.0), RP)
        window_b = validate_success(res, 201)
        assert window_b["status"] == "OPEN"

    def test_delivery_window_true_overlap_rejected(self, api):
        """PRD §3.4: "Two windows on the same route and date may not overlap;
        intervals are half-open, so adjacent windows where one ends exactly when
        the other begins are permitted, while a true overlap is rejected with
        `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/delivery_window_half_open_interval_overlap
        """
        route, _window_a = self._setup(api)
        res = api.create_delivery_window(create_delivery_window_payload(
            route["id"], service_date="2026-09-10", start_hour=11, end_hour=13,
            capacity_cord_equivalent=50.0), RP)
        validate_error(res, "ERR_WINDOW_OVERLAP", expected_status=409)


class TestWindowLockGatedByPayment:
    """Window OPEN -> LOCKED requires every SCHEDULED order in it to be PAID."""

    def _setup_two_scheduled_orders(self, api):
        set_clock("2026-08-01T00:00:00Z")
        customer, product, route = setup_catalog_with_route(
            postal_code="30015", prefixes=("3",), sku="P15", available_qty=100)
        window = create_window(route["id"], service_date="2026-08-25",
                               start_hour=8, end_hour=18, capacity=100.0)
        order_a = create_order(customer["id"], product["id"], 1.0,
                               postal_code="30015",
                               requested_delivery_date="2026-08-25")
        submit_and_pay(order_a["id"])
        schedule_order(order_a["id"], window["id"])
        order_b = create_order(customer["id"], product["id"], 1.0,
                               postal_code="30015",
                               requested_delivery_date="2026-08-25")
        submit_and_pay(order_b["id"])
        schedule_order(order_b["id"], window["id"])
        return customer, product, route, window, order_a, order_b

    def test_window_lock_succeeds_when_all_scheduled_orders_paid(self, api):
        """PRD §3.4: "Locking requires that every order scheduled in the window
        is already `PAID`."

        Design: Difficulty/cross_entity_state_dependency/window_lock_gated_by_child_order_payment_status
        """
        _c, _p, _r, window, _a, _b = self._setup_two_scheduled_orders(api)
        res = api.lock_delivery_window(window["id"], RP)
        locked = validate_success(res, 200)
        assert locked["status"] == "LOCKED"

    def test_window_lock_gated_by_child_order_payment_status(self, api):
        """PRD §3.4: "Locking requires that every order scheduled in the window
        is already `PAID`."
        PRD §2.8: "State permission: the target resource's current state permits
        the requested transition — otherwise `ERR_INVALID_STATE` (HTTP 409)."
        After a partial refund moves one scheduled order to PARTIALLY_REFUNDED,
        the lock is rejected.

        Design: Difficulty/cross_entity_state_dependency/window_lock_gated_by_child_order_payment_status
        """
        _c, _p, _r, window, _a, order_b = self._setup_two_scheduled_orders(api)
        order_b = get_success_data(api.get_order(order_b["id"], CS))
        invoice = get_success_data(api.list_invoices(
            CS, params={"order_id": order_b["id"]}))[0]
        get_success_data(api.post_payment(order_b["id"], create_payment_payload(
            "REFUND", 10000), CS))
        order_b = get_success_data(api.get_order(order_b["id"], CS))
        assert order_b["payment_status"] == "PARTIALLY_REFUNDED"
        assert order_b["fulfillment_status"] == "SCHEDULED"
        res = api.lock_delivery_window(window["id"], RP)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
