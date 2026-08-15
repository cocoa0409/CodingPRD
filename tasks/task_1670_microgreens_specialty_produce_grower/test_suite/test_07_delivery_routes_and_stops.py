"""Delivery routes: empty-route dispatch, the inclusive per-stop minimum at
dispatch, delivery gating on route state, and the order-cancel cascade onto
lines and stops."""
from test_helpers import (
    ApiErrorId,
    assert_delivery_route,
    assert_delivery_stop,
    create_delivery_route,
    dispatch_route,
    get_delivery_stop,
    get_standing_order,
    make_chef_headers,
    setup_confirmed_order,
    setup_route_with_stop,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import OPS


class TestDispatchPreconditions:
    def test_dispatch_route_without_scheduled_stops_rejected(self, api):
        """PRD §3.6: "Dispatching requires at least one stop still `SCHEDULED` —
        otherwise `ERR_EMPTY_ROUTE` — and moves the route from `PLANNED` to
        `DISPATCHED`."

        Design: Corner/validations/dispatch_empty_route_returns_empty_route
        """
        route = create_delivery_route(route_code="R-EMPTY",
                                      min_stop_subtotal_cents=100)
        assert route["status"] == "PLANNED"

        resp = api.dispatch_route(route["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_EMPTY_ROUTE)

        after = validate_success(api.get_delivery_route(route["id"], OPS))
        assert_delivery_route(after)
        assert after["status"] == "PLANNED", (
            "A rejected dispatch leaves the route PLANNED")


class TestStopMinimumBoundary:
    def _dispatched_stop(self, api, qty_kg, price, minimum):
        ws = setup_confirmed_order(name="Chard", crop_category="PETITE_GREEN",
                                   qty_kg=qty_kg, listed_price_cents_per_kg=price,
                                   days_to_harvest=13,
                                   expected_yield_grams_per_tray=11000)
        route, stop = setup_route_with_stop(ws, min_stop_subtotal_cents=minimum)
        ws["route"] = dispatch_route(route["id"])
        ws["stop"] = get_delivery_stop(stop["id"])
        return ws

    def test_stop_exactly_at_minimum_included(self, api):
        """PRD §3.6: "The minimum is then applied with an inclusive boundary: a
        stop whose `stop_subtotal_cents` is at least the route's
        `min_stop_subtotal_cents` becomes `INCLUDED`, and a stop below the
        minimum becomes `SKIPPED` — a stop landing exactly on the minimum is
        included."
        PRD §3.6: "As part of dispatch the system computes each stop's
        `stop_subtotal_cents` as the sum of the `line_extension_cents` over the
        stop's order lines, using the order's final, locked subtotal."

        Design: Difficulty/boundary_precision_check/delivery_stop_minimum_inclusive
        """
        ws = self._dispatched_stop(api, qty_kg=3.0, price=1000, minimum=3000)
        stop = ws["stop"]
        assert_delivery_stop(stop)
        assert stop["stop_subtotal_cents"] == 3000, "3.0 kg * 1000 c/kg"
        assert stop["outcome"] == "INCLUDED", "3000 >= 3000: the boundary is inclusive"

    def test_stop_one_cent_below_minimum_skipped(self, api):
        """PRD §3.6: "The minimum is then applied with an inclusive boundary: a
        stop whose `stop_subtotal_cents` is at least the route's
        `min_stop_subtotal_cents` becomes `INCLUDED`, and a stop below the
        minimum becomes `SKIPPED` — a stop landing exactly on the minimum is
        included."

        Design: Difficulty/boundary_precision_check/delivery_stop_minimum_inclusive
        """
        ws = self._dispatched_stop(api, qty_kg=2.999, price=1000, minimum=3000)
        stop = ws["stop"]
        assert stop["stop_subtotal_cents"] == 2999, (
            "2.999 kg * 1000 c/kg rounds to 2999 cents")
        assert stop["outcome"] == "SKIPPED", "2999 < 3000: one cent below is skipped"


class TestDeliverGating:
    def test_deliver_on_planned_route_rejected(self, api):
        """PRD §3.6: "marking an `INCLUDED` stop delivered requires the route to
        be `DISPATCHED` — a delivery attempt against a route in any other state
        is rejected with `ERR_ROUTE_NOT_DISPATCHED`."

        Design: Corner/state_machines/deliver_on_planned_route_returns_route_not_dispatched
        """
        ws = setup_confirmed_order(name="Basil2", crop_category="SPECIALTY_HERB",
                                   qty_kg=1.0, listed_price_cents_per_kg=2000,
                                   days_to_harvest=21,
                                   expected_yield_grams_per_tray=5000,
                                   min_order_grams=100)
        route, stop = setup_route_with_stop(ws, min_stop_subtotal_cents=100)
        assert route["status"] == "PLANNED"  # never dispatched

        resp = api.deliver_stop(stop["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_DISPATCHED)

        after = get_delivery_stop(stop["id"])
        assert after["outcome"] == "SCHEDULED", (
            "A rejected delivery leaves the stop SCHEDULED")


class TestOrderCancelCascade:
    def _confirmed_order_with_stop(self, api):
        ws = setup_confirmed_order(name="Kale", crop_category="PETITE_GREEN",
                                   qty_kg=1.0, listed_price_cents_per_kg=600,
                                   days_to_harvest=14,
                                   expected_yield_grams_per_tray=10000)
        route, stop = setup_route_with_stop(ws, min_stop_subtotal_cents=100)
        ws["route"] = route
        ws["stop"] = stop
        return ws

    def test_cancel_confirmed_order_shorts_lines(self, api):
        """PRD §3.5: "Cancelling a `CONFIRMED` order releases committed demand:
        every line still in `PLANNED` `fulfillment` becomes `SHORTED`, and any
        linked delivery stop's `outcome` is flipped to `SKIPPED`. Either way the
        order lands in the terminal `CANCELLED` state."

        Design: Difficulty/transitive_cascade/standing_order_cancel_cascade_items_and_stops
        """
        ws = self._confirmed_order_with_stop(api)
        assert ws["order_item"]["fulfillment"] == "PLANNED"

        cancelled = validate_success(api.cancel_standing_order(
            ws["standing_order"]["id"], make_chef_headers(ws["customer"]["id"])))
        assert cancelled["status"] == "CANCELLED"

        item_after = validate_success(
            api.get_order_item(ws["order_item"]["id"], OPS))
        assert item_after["fulfillment"] == "SHORTED", (
            "Cancel-release: the PLANNED line becomes SHORTED")

        order_after = get_standing_order(ws["standing_order"]["id"], ws["customer"])
        assert order_after["status"] == "CANCELLED"

    def test_cancel_confirmed_order_skips_linked_stop(self, api):
        """PRD §3.5: "Cancelling a `CONFIRMED` order releases committed demand:
        every line still in `PLANNED` `fulfillment` becomes `SHORTED`, and any
        linked delivery stop's `outcome` is flipped to `SKIPPED`. Either way the
        order lands in the terminal `CANCELLED` state."

        Design: Difficulty/transitive_cascade/standing_order_cancel_cascade_items_and_stops
        """
        ws = self._confirmed_order_with_stop(api)
        assert ws["stop"]["outcome"] == "SCHEDULED"

        validate_success(api.cancel_standing_order(
            ws["standing_order"]["id"], make_chef_headers(ws["customer"]["id"])))

        stop_after = get_delivery_stop(ws["stop"]["id"])
        assert stop_after["outcome"] == "SKIPPED", (
            "Cascade: the linked delivery stop is flipped to SKIPPED")
