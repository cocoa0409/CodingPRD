"""Delivery day: dispatch gating, moisture verification, delivery cascades
(PRD §3.4, §3.7, §2.8)."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_order_payload, order_line, set_clock, create_customer,
    create_product, create_route, create_window, create_order,
    setup_catalog_with_route, submit_and_pay, schedule_order,
    create_activated_subscription, deliver_scheduled_order,
    create_delivered_order, make_customer_headers,
    TEST_USERS,
)

CS = TEST_USERS["customer_service_headers"]
OM = TEST_USERS["operations_manager_headers"]
RP = TEST_USERS["route_planner_headers"]
DR = TEST_USERS["driver_headers"]


def _setup_scheduled_order(api, sku="P9", postal_code="60009", prefixes=("6",),
                           service_date="2026-08-20", window_hours=(8, 12)):
    """Order paid and scheduled into an OPEN window; clock still before cutoff."""
    set_clock("2026-08-01T00:00:00Z")
    customer, product, route = setup_catalog_with_route(
        postal_code=postal_code, prefixes=prefixes, sku=sku, available_qty=50)
    window = create_window(route["id"], service_date=service_date,
                           start_hour=window_hours[0], end_hour=window_hours[1],
                           capacity=50.0)
    order = create_order(customer["id"], product["id"], 1.0,
                         postal_code=postal_code,
                         requested_delivery_date=service_date)
    submit_and_pay(order["id"])
    schedule_order(order["id"], window["id"])
    return customer, product, route, window, order


class TestWindowLockCascade:
    def test_dispatch_rejected_while_window_open(self, api):
        """PRD §3.7: "Dispatch moves a `SCHEDULED` order to `OUT_FOR_DELIVERY`
        and is permitted only when the bound window is `LOCKED`, the logical
        date equals the window's `service_date`, and the logical hour is at or
        after `start_hour` and strictly before `end_hour`."
        PRD §2.5: "Crossing a delivery window's day-before cutoff — 18:00
        local time on the day before the window's `service_date` —
        automatically locks that window."
        An OPEN window holding a paid scheduled order cannot survive to its
        service date (the day-before cutoff auto-lock fires first), so the
        not-LOCKED dispatch gate is exercised with a manually CLOSED window:
        the date and hour conditions are met, but the window is not LOCKED, so
        the dispatch is rejected ERR_INVALID_STATE.

        Design: Difficulty/transitive_cascade/window_lock_cascade_window_order_delivery_eligibility
        """
        _c, _p, _r, window, order = _setup_scheduled_order(api)
        get_success_data(api.close_delivery_window(window["id"], RP))
        set_clock("2026-08-20T09:00:00Z")
        res = api.dispatch_order(order["id"], DR)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_window_lock_cascade_window_order_delivery_eligibility(self, api):
        """PRD §3.4: "a planner may also lock an `OPEN` or `CLOSED` window
        manually."
        PRD §3.7: "Dispatch moves a `SCHEDULED` order to `OUT_FOR_DELIVERY` and
        is permitted only when the bound window is `LOCKED`, the logical date
        equals the window's `service_date`, and the logical hour is at or after
        `start_hour` and strictly before `end_hour`."
        PRD §2.5: "Crossing a delivery window's day-before cutoff — 18:00
        local time on the day before the window's `service_date` —
        automatically locks that window."
        With the window manually CLOSED (so the cutoff auto-lock does not
        apply) the dispatch fails; locking the window then enables the
        previously-failing dispatch.

        Design: Difficulty/transitive_cascade/window_lock_cascade_window_order_delivery_eligibility
        """
        _c, _p, _r, window, order = _setup_scheduled_order(api)
        get_success_data(api.close_delivery_window(window["id"], RP))
        set_clock("2026-08-20T09:00:00Z")
        res = api.dispatch_order(order["id"], DR)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        locked = validate_success(api.lock_delivery_window(window["id"], RP), 200)
        assert locked["status"] == "LOCKED"
        dispatched = validate_success(api.dispatch_order(order["id"], DR), 200)
        assert dispatched["fulfillment_status"] == "OUT_FOR_DELIVERY"


class TestDispatchPreconditions:
    def test_dispatch_requires_window_locked_and_time_in_window(self, api):
        """PRD §3.7: "Dispatch moves a `SCHEDULED` order to `OUT_FOR_DELIVERY`
        and is permitted only when the bound window is `LOCKED`, the logical
        date equals the window's `service_date`, and the logical hour is at or
        after `start_hour` and strictly before `end_hour`."
        The window is LOCKED and the date matches, but the logical hour 14 is
        outside [8, 12).

        Design: Corner/state_machines/dispatch_requires_window_locked_and_time_in_window
        """
        _c, _p, _r, window, order = _setup_scheduled_order(
            api, sku="PDP", postal_code="01010", prefixes=("0",),
            service_date="2026-08-15", window_hours=(8, 12))
        get_success_data(api.lock_delivery_window(window["id"], RP))
        set_clock("2026-08-15T14:00:00Z")
        res = api.dispatch_order(order["id"], DR)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_order_deliver_from_confirmed_invalid_state(self, api):
        """PRD §3.7: delivery completion is the OUT_FOR_DELIVERY -> DELIVERED
        transition, and §2.8: "State permission: the target resource's current
        state permits the requested transition — otherwise `ERR_INVALID_STATE`
        (HTTP 409)." A CONFIRMED order cannot be delivered directly.

        Design: Corner/state_machines/order_deliver_from_confirmed_invalid_state
        """
        set_clock("2026-08-01T00:00:00Z")
        customer, product, _route = setup_catalog_with_route(sku="PIT")
        order = create_order(customer["id"], product["id"], 1.0)
        submit_and_pay(order["id"])
        order = get_success_data(api.get_order(order["id"], CS))
        assert order["fulfillment_status"] == "CONFIRMED"
        res = api.deliver_order(order["id"], DR)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)


class TestMoistureBoundary:
    def _setup_out_for_delivery(self, api):
        customer, product, route = setup_catalog_with_route(
            postal_code="10013", prefixes=("1",), sku="P13", available_qty=10,
            capacity=50.0)
        window = create_window(route["id"], service_date="2026-08-15",
                               start_hour=8, end_hour=18, capacity=50.0)
        order = create_order(customer["id"], product["id"], 1.0,
                             postal_code="10013",
                             requested_delivery_date="2026-08-15")
        submit_and_pay(order["id"])
        schedule_order(order["id"], window["id"])
        get_success_data(api.lock_delivery_window(window["id"], RP))
        set_clock("2026-08-15T10:00:00Z")
        get_success_data(api.dispatch_order(order["id"], DR))
        lines = get_success_data(api.list_order_lines(order["id"], DR))
        return customer, product, window, order, lines[0]

    def test_moisture_reading_at_ceiling_passes(self, api):
        """PRD §3.7: "the reading passes when `moisture_pct` is less than or
        equal to the line product's `moisture_ceiling_pct` — a reading exactly
        at the ceiling passes."

        Design: Difficulty/boundary_precision_check/moisture_ceiling_inclusive_equality
        """
        _c, _p, _w, _o, line = self._setup_out_for_delivery(api)
        res = api.create_moisture_reading(line["id"], {"moisture_pct": 20.0}, DR)
        reading = validate_success(res, 201)
        assert reading["reading_pass"] is True

    def test_moisture_reading_above_ceiling_fails(self, api):
        """PRD §3.7: "the reading passes when `moisture_pct` is less than or
        equal to the line product's `moisture_ceiling_pct` — a reading exactly
        at the ceiling passes." A reading of ceiling + 0.1 fails.

        Design: Difficulty/boundary_precision_check/moisture_ceiling_inclusive_equality
        """
        _c, _p, _w, _o, line = self._setup_out_for_delivery(api)
        res = api.create_moisture_reading(line["id"], {"moisture_pct": 20.1}, DR)
        reading = validate_success(res, 201)
        assert reading["reading_pass"] is False


class TestTerminalStateLockdown:
    def test_terminal_state_lockdown_delivered_order_cannot_be_cancelled(self, api):
        """PRD §3.8: "an attempt from `OUT_FOR_DELIVERY`, `DELIVERED`, or
        `CANCELLED` is rejected with `ERR_NOT_CANCELLABLE`."

        Design: Corner/state_machines/terminal_state_lockdown_delivered_order_cannot_be_cancelled
        """
        set_clock("2026-08-01T00:00:00Z")
        customer, product, route = setup_catalog_with_route(
            postal_code="01010", prefixes=("0",), sku="PTL", available_qty=10,
            capacity=50.0)
        order, _window = create_delivered_order(
            customer["id"], product["id"], 1.0, route, postal_code="01010",
            service_date="2026-08-15")
        assert order["fulfillment_status"] == "DELIVERED"
        res = api.cancel_order(order["id"], {"reason": "too late"},
                               make_customer_headers(customer["id"]))
        validate_error(res, "ERR_NOT_CANCELLABLE", expected_status=409)


class TestDeliverCascade:
    """Driver POST /deliver cascades: subscription accrual -> FULFILLED
    threshold crossing, and customer lifetime CE -> loyalty tier recompute."""

    def _setup_cascade(self, api):
        set_clock("2026-10-01T00:00:00Z")
        customer = create_customer(postal_code="50008")
        subscription = create_activated_subscription(
            customer["id"], tier="ESTATE", season_year=2026,
            commitment_cord_equivalent=8.0, prepaid_cents=0, discount_pct=0.12)
        product = create_product(sku="P8", product_kind="CORD", species="OAK",
                                 seasoned_grade="KILN_DRIED", base_price_cents=40000,
                                 moisture_ceiling_pct=20.0, available_qty=200)
        route = create_route(route_code="R8", depot_name="West",
                             prefixes=("5",), capacity=200.0)
        # First delivery: 7.5 CE inside the season window.
        order_a, _wa = create_delivered_order(
            customer["id"], product["id"], 7.5, route, postal_code="50008",
            service_date="2026-11-15", subscription_id=subscription["id"])
        # Trigger order: 2.5 CE, scheduled and dispatched but not yet delivered.
        window_b = create_window(route["id"], service_date="2026-12-10",
                                 start_hour=8, end_hour=18, capacity=200.0)
        order_b = create_order(customer["id"], product["id"], 2.5,
                               postal_code="50008",
                               requested_delivery_date="2026-12-10",
                               subscription_id=subscription["id"])
        submit_and_pay(order_b["id"])
        schedule_order(order_b["id"], window_b["id"])
        get_success_data(api.lock_delivery_window(window_b["id"], RP))
        set_clock("2026-12-10T10:00:00Z")
        get_success_data(api.dispatch_order(order_b["id"], DR))
        lines = get_success_data(api.list_order_lines(order_b["id"], DR))
        get_success_data(api.create_moisture_reading(
            lines[0]["id"], {"moisture_pct": 18.0}, DR))
        return customer, subscription, product, route, order_a, order_b

    def test_deliver_cascade_order_subscription_customer_loyalty(self, api):
        """PRD §3.3: "The moment a delivery pushes `delivered_cord_equivalent`
        to at least `commitment_cord_equivalent`, the subscription
        auto-transitions from `ACTIVE` to `FULFILLED` with `closed_at` set to
        that delivery's timestamp."
        PRD §3.7: "when the order references an `ACTIVE` subscription and the
        delivery falls inside the season window — the subscription's
        `delivered_cord_equivalent` grows by the same amount, its `version`
        incrementing; crossing the commitment threshold in that instant chains
        the subscription to `FULFILLED`."

        Design: Difficulty/transitive_cascade/deliver_cascade_order_subscription_customer_loyalty
        """
        customer, subscription, _p, _r, _oa, order_b = self._setup_cascade(api)
        delivered = validate_success(api.deliver_order(order_b["id"], DR), 200)
        assert delivered["fulfillment_status"] == "DELIVERED"
        sub_after = get_success_data(api.get_subscription(subscription["id"], CS))
        assert sub_after["delivered_cord_equivalent"] == pytest.approx(10.0)
        assert sub_after["status"] == "FULFILLED"

    def test_deliver_cascade_recomputes_loyalty_tier(self, api):
        """PRD §3.7: "the customer's `lifetime_cord_equivalent_delivered` grows
        by the order's `total_cord_equivalent` with `loyalty_tier` recomputed
        and the customer's `version` incremented, and — when the order
        references an `ACTIVE` subscription and the delivery falls inside the
        season window — the subscription's `delivered_cord_equivalent` grows by
        the same amount, its `version` incrementing; crossing the commitment
        threshold in that instant chains the subscription to `FULFILLED`."
        PRD §3.1: "below 4.0 cord-equivalents the customer is `STANDARD`, from
        4.0 up to but not including 10.0 they are `SILVER`, and at 10.0 or more
        they are `GOLD`."
        The 2.5 CE delivery lifts lifetime CE from 7.5 to exactly 10.0 -> GOLD.

        Design: Difficulty/transitive_cascade/deliver_cascade_order_subscription_customer_loyalty
        """
        customer, subscription, product, _r, _oa, order_b = self._setup_cascade(api)
        validate_success(api.deliver_order(order_b["id"], DR), 200)
        customer_after = get_success_data(api.get_customer(customer["id"], CS))
        assert customer_after["lifetime_cord_equivalent_delivered"] == pytest.approx(10.0)
        assert customer_after["loyalty_tier"] == "GOLD"
        product_after = get_success_data(api.get_product(product["id"], OM))
        assert product_after["reserved_qty"] == pytest.approx(0.0)
