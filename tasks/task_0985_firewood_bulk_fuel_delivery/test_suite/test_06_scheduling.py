"""Scheduling: capacity boundary, provisional-vs-final delivery fee, validation
priority, OCC stale version, RBAC (PRD §2.7, §2.8, §3.6, §3.7)."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_order_payload, order_line, create_payment_payload,
    set_clock, create_customer, create_product, create_route, create_window,
    create_order, setup_catalog_with_route, submit_and_pay, schedule_order,
    pay_order_in_full, TEST_USERS,
)

CS = TEST_USERS["customer_service_headers"]
OM = TEST_USERS["operations_manager_headers"]
RP = TEST_USERS["route_planner_headers"]
DR = TEST_USERS["driver_headers"]


class TestWindowCapacityEqualityBoundary:
    def _setup_order_at_capacity(self, api):
        set_clock("2026-08-01T00:00:00Z")
        customer, product, route = setup_catalog_with_route(
            postal_code="90012", prefixes=("9",), sku="P12", available_qty=10,
            capacity=5.0)
        window = create_window(route["id"], service_date="2026-08-15",
                               start_hour=8, end_hour=18, capacity=3.0)
        order = create_order(customer["id"], product["id"], 3.0,
                             postal_code="90012",
                             requested_delivery_date="2026-08-15")
        submit_and_pay(order["id"])
        return customer, product, route, window, order

    def test_window_capacity_equality_permitted_boundary(self, api):
        """PRD §2.8: "Window capacity: the window's committed volume plus the
        order's total volume does not exceed the window's capacity, with exact
        equality permitted — otherwise `ERR_WINDOW_CAPACITY_EXCEEDED`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/window_capacity_equality_permitted_boundary
        """
        _c, _p, _r, window, order = self._setup_order_at_capacity(api)
        scheduled = schedule_order(order["id"], window["id"])
        assert scheduled["fulfillment_status"] == "SCHEDULED"
        window_after = get_success_data(api.get_delivery_window(window["id"], RP))
        assert window_after["committed_cord_equivalent"] == pytest.approx(3.0)

    def test_window_auto_closes_when_committed_reaches_capacity(self, api):
        """PRD §3.4: "A planner may close an `OPEN` window manually, and the
        system auto-closes one the moment its committed volume reaches its
        capacity; either way the window becomes `CLOSED` and refuses further
        scheduling."

        Design: Difficulty/boundary_precision_check/window_capacity_equality_permitted_boundary
        """
        _c, _p, _r, window, order = self._setup_order_at_capacity(api)
        schedule_order(order["id"], window["id"])
        window_after = get_success_data(api.get_delivery_window(window["id"], RP))
        assert window_after["status"] == "CLOSED"


class TestDeliveryFeeProvisionalVsFinal:
    """Provisional fee uses longest-prefix route pick; final fee uses the bound
    window's route regardless of prefix ranking (PRD §3.6)."""

    def _setup_two_routes(self, api):
        set_clock("2026-08-01T00:00:00Z")
        customer = create_customer(postal_code="01234", full_name="Cu One",
                                   email="cu1@x.com", street_address="1 Main")
        product = create_product(sku="P1", product_kind="CORD", species="OAK",
                                 seasoned_grade="KILN_DRIED", base_price_cents=40000,
                                 moisture_ceiling_pct=20.0, available_qty=10)
        # Zone A route: matched prefix "01234" (length 5) -> 4500
        route_a = create_route(route_code="A1", depot_name="North",
                               prefixes=("01234",), capacity=10.0)
        # Zone C route: matched prefix "0" (length 1) -> 9500
        route_c = create_route(route_code="C1", depot_name="Far",
                               prefixes=("0",), capacity=10.0)
        window_c = create_window(route_c["id"], service_date="2026-08-10",
                                 start_hour=8, end_hour=12, capacity=10.0)
        return customer, product, route_a, route_c, window_c

    def test_delivery_fee_provisional_pick_uses_longest_prefix(self, api):
        """PRD §3.6: "Before the order is scheduled, the fee is provisional:
        the system selects among active routes by longest-prefix match against
        `delivery_postal_code` with the tie-breaks of §3.4, and an empty
        candidate set rejects the pricing with `ERR_NO_ROUTE`."
        PRD §3.6: "The base zone fee is set by the length of the matched prefix:
        five characters or more is zone A at 4,500 cents, three or four
        characters is zone B at 6,500 cents, and one or two characters is zone
        C at 9,500 cents."
        Postal 01234 matches prefix "01234" (length 5) on route A1 and prefix
        "0" (length 1) on route C1; longest prefix wins, so the provisional fee
        is the zone A fee 4500.

        Design: Difficulty/dual_variant_calc/delivery_fee_provisional_vs_final_diverge_on_route_binding
        """
        customer, product, _ra, _rc, _wc = self._setup_two_routes(api)
        res = api.create_order(create_order_payload(
            customer["id"], [order_line(product["id"], 1.0)],
            delivery_street_address="1 Main", delivery_postal_code="01234",
            requested_delivery_date="2026-08-10"), CS)
        order = validate_success(res, 201)
        assert order["delivery_fee_cents"] == 4500

    def test_delivery_fee_final_uses_bound_route_and_diverges(self, api):
        """PRD §3.6: "Once the order is scheduled, the fee is final and is
        computed from the route of the bound delivery window regardless of
        prefix ranking, so it may diverge from the provisional figure."
        Binding the order to a window on route C1 (matched prefix "0", length 1,
        zone C at 9,500 cents) moves the fee from 4500 to 9500.

        Design: Difficulty/dual_variant_calc/delivery_fee_provisional_vs_final_diverge_on_route_binding
        """
        customer, product, _ra, _rc, window_c = self._setup_two_routes(api)
        res = api.create_order(create_order_payload(
            customer["id"], [order_line(product["id"], 1.0)],
            delivery_street_address="1 Main", delivery_postal_code="01234",
            requested_delivery_date="2026-08-10"), CS)
        order = validate_success(res, 201)
        provisional_fee = order["delivery_fee_cents"]
        assert provisional_fee == 4500
        submit_and_pay(order["id"])
        scheduled = schedule_order(order["id"], window_c["id"])
        assert scheduled["delivery_fee_cents"] == 9500
        assert scheduled["delivery_fee_cents"] != provisional_fee


class TestScheduleValidationPriority:
    def _setup_past_window(self, api):
        # Build the window and order while the clock is before the service
        # date, then advance the clock past it.
        set_clock("2026-06-15T00:00:00Z")
        customer, product, route = setup_catalog_with_route(
            postal_code="70010", prefixes=("7",), sku="P10", available_qty=10)
        window = create_window(route["id"], service_date="2026-07-01",
                               start_hour=8, end_hour=12, capacity=50.0)
        order = create_order(customer["id"], product["id"], 1.0,
                             postal_code="70010",
                             requested_delivery_date="2026-07-01")
        set_clock("2026-08-01T00:00:00Z")
        return customer, product, route, window, order

    def test_state_vs_business_temporal_on_schedule_call(self, api):
        """PRD §2.8: "Incoming requests are validated against the following
        checks in strict priority order; when several checks would fail, the
        failure with the lowest priority number produces the response, so an
        earlier failure is never masked by a later one."
        The order is still DRAFT (state check, priority 5) and the window is
        past-dated (temporal check, priority 13); the state failure wins with
        ERR_INVALID_STATE.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_schedule_call
        """
        _c, _p, _r, window, order = self._setup_past_window(api)
        order = get_success_data(api.get_order(order["id"], RP))
        res = api.schedule_order(order["id"], {
            "delivery_window_id": window["id"],
            "expected_order_version": order["version"]}, RP)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_temporal_failure_alone_surfaces_window_closed_error(self, api):
        """PRD §2.8: "Window temporal rules: a window's `service_date` is not
        in the past, its `end_hour` is strictly greater than its `start_hour`,
        and scheduling happens strictly before the day-before cutoff — otherwise
        `ERR_WINDOW_CLOSED_FOR_SCHEDULING` (HTTP 422)."
        With the order properly CONFIRMED (state check passes), the past-dated
        window alone fails at priority 13.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_schedule_call
        """
        set_clock("2026-06-15T00:00:00Z")
        customer, product, route = setup_catalog_with_route(
            postal_code="70010", prefixes=("7",), sku="P10", available_qty=10)
        window = create_window(route["id"], service_date="2026-07-01",
                               start_hour=8, end_hour=12, capacity=50.0)
        order = create_order(customer["id"], product["id"], 1.0,
                             postal_code="70010",
                             requested_delivery_date="2026-07-01")
        submit_and_pay(order["id"])
        set_clock("2026-08-01T00:00:00Z")
        order = get_success_data(api.get_order(order["id"], RP))
        res = api.schedule_order(order["id"], {
            "delivery_window_id": window["id"],
            "expected_order_version": order["version"]}, RP)
        validate_error(res, "ERR_WINDOW_CLOSED_FOR_SCHEDULING", expected_status=422)


class TestOccStaleVersionOnSchedule:
    def test_occ_stale_version_on_schedule(self, api):
        """PRD §2.7: "Scheduling an order into a delivery window — whether the
        initial scheduling of a `CONFIRMED` order or the rescheduling of a
        `DELIVERY_FAILED` one — requires the request to carry
        `expected_order_version` equal to the order's current `version`. A
        mismatch means a pricing-relevant mutation (an add-on toggle, a line
        edit, a subscription attach, a refund, a cancellation-fee application)
        has advanced the order since the client last read it, and the request
        is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than planned
        against stale capacity math."
        The intervening mutation here is a partial refund, which increments the
        order's version.

        Design: Corner/cross_cutting_layers/occ_stale_version_on_schedule
        """
        set_clock("2026-08-01T00:00:00Z")
        customer, product, route = setup_catalog_with_route(
            sku="POCC", available_qty=50)
        window = create_window(route["id"], service_date="2026-08-15",
                               start_hour=8, end_hour=18, capacity=50.0)
        order = create_order(customer["id"], product["id"], 1.0)
        submit_and_pay(order["id"])
        order = get_success_data(api.get_order(order["id"], RP))
        stale_version = order["version"]
        # Intervening mutation: partial refund advances Order.version.
        get_success_data(api.post_payment(order["id"], create_payment_payload(
            "REFUND", 1000), CS))
        res = api.schedule_order(order["id"], {
            "delivery_window_id": window["id"],
            "expected_order_version": stale_version}, RP)
        validate_error(res, "ERR_STALE_VERSION", expected_status=412)


class TestScheduleRbac:
    def test_driver_cannot_schedule_orders(self, api):
        """PRD §2.1: "A request whose role is not permitted on the target
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /api/v1/orders/{id}/schedule — Authorized Role(s):
        RoutePlanner.

        Design: Corner/rbac/driver_cannot_schedule_orders
        """
        set_clock("2026-08-01T00:00:00Z")
        customer, product, route = setup_catalog_with_route(sku="PDR")
        window = create_window(route["id"], service_date="2026-08-15",
                               start_hour=8, end_hour=18, capacity=50.0)
        order = create_order(customer["id"], product["id"], 1.0)
        submit_and_pay(order["id"])
        order = get_success_data(api.get_order(order["id"], RP))
        res = api.schedule_order(order["id"], {
            "delivery_window_id": window["id"],
            "expected_order_version": order["version"]}, DR)
        validate_error(res, "ERR_UNAUTHORIZED", expected_status=403)
