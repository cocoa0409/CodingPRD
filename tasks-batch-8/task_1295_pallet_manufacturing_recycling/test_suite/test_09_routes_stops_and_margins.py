"""Delivery routes: margins (provisional vs final), cube gate, sequencing."""
import pytest

from test_helpers import (
    FLEET,
    ApiErrorId,
    add_route_stop,
    api_client,
    arrive_stop,
    complete_stop,
    create_allocated_order,
    create_confirmed_order,
    create_route,
    dispatch_route_current_version,
    get_route,
    setup_sellable_world,
    validate_error,
    validate_success,
)


def _setup_two_allocated_orders(company="ShipperOne", qty1=20, qty2=15):
    """Sellable world + two allocated NEW orders. Returns (spec, o1, o2)."""
    spec, _lot, customer = setup_sellable_world(company, lot_quantity=500)
    o1 = create_allocated_order(customer["id"], spec["id"], qty1)
    o2 = create_allocated_order(customer["id"], spec["id"], qty2)
    return spec, o1, o2


def _setup_route_with_two_stops(planned_miles=120):
    spec, o1, o2 = _setup_two_allocated_orders()
    route = create_route(trailer_cube_capacity_cuft=5000,
                         planned_miles=planned_miles)
    stop1 = add_route_stop(route["id"], 1, "DELIVERY", order_id=o1["id"])
    stop2 = add_route_stop(route["id"], 2, "DELIVERY", order_id=o2["id"])
    return o1, o2, route, stop1, stop2


class TestRouteMarginDualVariant:

    def test_dispatch_computes_provisional_margin_from_scheduled_stops(self):
        """PRD §3.8: "Dispatch computes the route's `provisional_margin_cents`:
        revenue is the sum over `SCHEDULED` stops of type `DELIVERY` or `MIXED`
        of their orders' `total_cents`; cost is the `planned_miles` times one
        hundred eighty-five cents per mile, rounded half-up, plus a fixed
        forty-five hundred cents per stop across all stops; the margin is
        revenue minus cost."
        PRD §3.8: "In the same motion, every stop's order moves from
        `ALLOCATED` to `SHIPPED`, the lines on those stops move from
        `ALLOCATED` to `FULFILLED`, and the route's `version` increments as it
        becomes `DISPATCHED`."

        Design: Difficulty/dual_variant_calc/route_margin_provisional_vs_final_with_skip
        """
        o1, o2, route, _s1, _s2 = _setup_route_with_two_stops()
        assert o1["total_cents"] == 30000  # 20 * 1500
        assert o2["total_cents"] == 22500  # 15 * 1500
        dispatched = dispatch_route_current_version(route["id"])
        assert dispatched["status"] == "DISPATCHED"
        # revenue 52500 - (120 * 185 + 2 * 4500) = 52500 - 31200 = 21300
        assert dispatched["provisional_margin_cents"] == 21300, (
            f"expected provisional margin 21300, "
            f"got {dispatched['provisional_margin_cents']}"
        )
        o1_after = validate_success(api_client.get_order(o1["id"], FLEET))
        o2_after = validate_success(api_client.get_order(o2["id"], FLEET))
        assert o1_after["fulfillment_status"] == "SHIPPED"
        assert o2_after["fulfillment_status"] == "SHIPPED"

    def test_close_computes_final_margin_zeroing_skipped_stop(self):
        """PRD §3.8: "The `final_margin_cents` mirrors the provisional shape
        with actuals substituted: only `COMPLETED` stops deliver revenue
        (`SKIPPED` stops contribute zero), the mileage and per-stop costs stand
        as before, the `fuel_surcharge_cents` is added to cost, and every pool
        return `CREDITED` on this route's stops adds its `total_credit_cents`
        as a cost of credit owed back to customers."
        PRD §3.8: "The `provisional_margin_cents` is retained untouched so
        planning variance is reportable; identical route data yields different
        provisional and final margins whenever a stop is skipped, a surcharge
        exists, or a pickup credits on the route."

        Design: Difficulty/dual_variant_calc/route_margin_provisional_vs_final_with_skip
        """
        o1, o2, route, stop1, stop2 = _setup_route_with_two_stops()
        dispatch_route_current_version(route["id"])
        skip_resp = api_client.skip_stop(stop2["id"], FLEET)
        validate_success(skip_resp)
        arrive_stop(stop1["id"])
        complete_stop(stop1["id"])
        resp = api_client.close_route(route["id"], {"fuel_surcharge_cents": 8000},
                                      FLEET)
        closed = validate_success(resp)
        assert closed["status"] == "CLOSED"
        # final: 30000 - (22200 + 9000 + 8000) = -9200; skipped stop2 adds 0.
        assert closed["final_margin_cents"] == -9200, (
            f"expected final margin -9200, got {closed['final_margin_cents']}"
        )
        assert closed["provisional_margin_cents"] == 21300, (
            "provisional margin must be retained untouched for variance "
            "reporting"
        )
        stop2_after = validate_success(
            api_client.get_route_stop(stop2["id"], FLEET))
        assert stop2_after["status"] == "SKIPPED"


class TestTrailerCubeBoundary:

    def _setup_cube_world(self):
        """Lot of 500 + allocated orders of 74, 1, and 1 pallet."""
        spec, _lot, customer = setup_sellable_world("CubeTest",
                                                    lot_quantity=500)
        o1 = create_allocated_order(customer["id"], spec["id"], 74)
        o2 = create_allocated_order(customer["id"], spec["id"], 1)
        o3 = create_allocated_order(customer["id"], spec["id"], 1)
        route = create_route(trailer_cube_capacity_cuft=500.0025,
                             planned_miles=40)
        return spec, o1, o2, o3, route

    def test_stop_bringing_cube_to_exact_capacity_admitted(self):
        """PRD §2.10: "A delivery route declares `trailer_cube_capacity_cuft`,
        the usable cube of its trailer, and accumulates `cube_used_cuft` as
        stops are added; a stop whose load would push `cube_used_cuft` beyond
        `trailer_cube_capacity_cuft` is rejected with `ERR_CUBE_OVERFLOW`, and
        the same ceiling is re-verified at dispatch time."
        PRD §3.8: "A delivery stop's `load_cube_cuft` is computed as the sum
        over the order's allocated lines of each line's `quantity` times its
        spec's `unit_cube_cuft`"

        Design: Difficulty/boundary_precision_check/trailer_cube_exact_fit_vs_overflow
        """
        _spec, o1, o2, _o3, route = self._setup_cube_world()
        stop1 = add_route_stop(route["id"], 1, "DELIVERY", order_id=o1["id"])
        # 74 * 6.6667 = 493.3358
        assert stop1["load_cube_cuft"] == pytest.approx(493.3358, abs=1e-4), (
            f"stop1 load must be 74 * 6.6667 = 493.3358, "
            f"got {stop1['load_cube_cuft']}"
        )
        # Exact fit: 493.3358 + 6.6667 == 500.0025 <= capacity -> admitted.
        stop2 = add_route_stop(route["id"], 2, "DELIVERY", order_id=o2["id"])
        assert stop2["load_cube_cuft"] == pytest.approx(6.6667, abs=1e-4)
        after = get_route(route["id"])
        assert after["cube_used_cuft"] == pytest.approx(500.0025, abs=1e-4), (
            f"cube_used must reach exactly capacity, "
            f"got {after['cube_used_cuft']}"
        )

    def test_stop_one_pallet_over_capacity_rejected_no_partial_mutation(self):
        """PRD §2.10: "a stop whose load would push `cube_used_cuft` beyond
        `trailer_cube_capacity_cuft` is rejected with `ERR_CUBE_OVERFLOW`"

        Design: Difficulty/boundary_precision_check/trailer_cube_exact_fit_vs_overflow
        """
        _spec, o1, o2, o3, route = self._setup_cube_world()
        add_route_stop(route["id"], 1, "DELIVERY", order_id=o1["id"])
        add_route_stop(route["id"], 2, "DELIVERY", order_id=o2["id"])
        # 500.0025 + 6.6667 > 500.0025 -> overflow
        resp = api_client.add_route_stop(
            route["id"],
            {"stop_sequence": 3, "stop_type": "DELIVERY", "order_id": o3["id"]},
            FLEET,
        )
        validate_error(resp, ApiErrorId.ERR_CUBE_OVERFLOW)
        assert resp.status_code == 422
        after = get_route(route["id"])
        assert after["cube_used_cuft"] == pytest.approx(500.0025, abs=1e-4), (
            f"rejected stop must not mutate cube_used_cuft, "
            f"got {after['cube_used_cuft']}"
        )


class TestStopSequencing:

    def _setup_three_stop_dispatched_route(self):
        spec, _lot, customer = setup_sellable_world("SeqTest",
                                                    lot_quantity=100)
        o1 = create_allocated_order(customer["id"], spec["id"], 1)
        o2 = create_allocated_order(customer["id"], spec["id"], 1)
        o3 = create_allocated_order(customer["id"], spec["id"], 1)
        route = create_route()
        s1 = add_route_stop(route["id"], 1, "DELIVERY", order_id=o1["id"])
        s2 = add_route_stop(route["id"], 2, "DELIVERY", order_id=o2["id"])
        s3 = add_route_stop(route["id"], 3, "DELIVERY", order_id=o3["id"])
        dispatch_route_current_version(route["id"])
        return s1, s2, s3

    def test_arrive_out_of_sequence_rejected(self):
        """PRD §3.8: "Arrival requires the stop `SCHEDULED` (else
        `ERR_STOP_NOT_SCHEDULED`), the owning route `DISPATCHED` (else
        `ERR_ROUTE_NOT_DISPATCHED`), and strict sequencing: every stop on the
        same route with a lower `stop_sequence` must already be `COMPLETED` or
        `SKIPPED`, else `ERR_STOP_OUT_OF_SEQUENCE`."

        Design: Difficulty/cross_entity_state_dependency/stop_arrive_gated_by_route_and_sibling_stops
        """
        s1, s2, _s3 = self._setup_three_stop_dispatched_route()
        # stop1 still SCHEDULED -> stop2 cannot arrive.
        resp = api_client.arrive_stop(s2["id"], FLEET)
        validate_error(resp, ApiErrorId.ERR_STOP_OUT_OF_SEQUENCE)
        assert resp.status_code == 409
        after = validate_success(api_client.get_route_stop(s2["id"], FLEET))
        assert after["status"] == "SCHEDULED", (
            f"rejected arrive must leave the stop SCHEDULED, "
            f"got {after['status']}"
        )

    def test_arrive_in_sequence_after_prior_completed_succeeds(self):
        """PRD §3.8: "On the road, stops progress `SCHEDULED` → `ARRIVED` →
        `COMPLETED`, with `SKIPPED` as the escape."
        PRD §3.8: "strict sequencing: every stop on the same route with a lower
        `stop_sequence` must already be `COMPLETED` or `SKIPPED`, else
        `ERR_STOP_OUT_OF_SEQUENCE`."

        Design: Difficulty/cross_entity_state_dependency/stop_arrive_gated_by_route_and_sibling_stops
        """
        s1, s2, _s3 = self._setup_three_stop_dispatched_route()
        arrive_stop(s1["id"])
        complete_stop(s1["id"])
        arrived2 = arrive_stop(s2["id"])
        assert arrived2["status"] == "ARRIVED", (
            "with stop1 COMPLETED, stop2 arrival is sequence-legal"
        )


class TestDispatchAndCloseGates:

    def test_dispatch_with_unallocated_order_rejected(self):
        """PRD §3.8: "Dispatch commits the plan. It requires `PLAN` status
        (else `ERR_ROUTE_NOT_PLAN`), at least one stop (else
        `ERR_ROUTE_EMPTY`), the cube ceiling re-verified (else
        `ERR_CUBE_OVERFLOW`), every stop's order already `ALLOCATED` (else
        `ERR_ORDER_NOT_ALLOCATED`)"

        Design: Corner/state_machines/route_dispatch_requires_order_allocated
        """
        spec, _lot, customer = setup_sellable_world("GuardCust",
                                                    lot_quantity=500)
        order = create_confirmed_order(customer["id"], spec["id"], 1)
        route = create_route()
        add_route_stop(route["id"], 1, "DELIVERY", order_id=order["id"])
        current = get_route(route["id"])
        resp = api_client.dispatch_route(
            route["id"], {"expected_route_version": current["version"]},
            FLEET)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_ALLOCATED)
        assert resp.status_code == 409
        after = get_route(route["id"])
        assert after["status"] == "PLAN"

    def test_duplicate_stop_sequence_rejected(self):
        """PRD §3.8: "Stops join a `PLAN` route — against any other route state
        the add fails with `ERR_INVALID_STATE` — each carrying a
        `stop_sequence` (one or greater, unique within the route; a duplicate
        is rejected with `ERR_DUPLICATE_STOP_SEQUENCE`)"

        Design: Corner/validations/duplicate_stop_sequence_rejected
        """
        route = create_route()
        add_route_stop(route["id"], 1, "PICKUP")
        resp = api_client.add_route_stop(
            route["id"], {"stop_sequence": 1, "stop_type": "PICKUP"}, FLEET)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_STOP_SEQUENCE)
        assert resp.status_code == 409

    def test_dispatch_empty_route_rejected(self):
        """PRD §3.8: "Dispatch commits the plan. It requires `PLAN` status
        (else `ERR_ROUTE_NOT_PLAN`), at least one stop (else
        `ERR_ROUTE_EMPTY`), the cube ceiling re-verified (else
        `ERR_CUBE_OVERFLOW`), every stop's order already `ALLOCATED` (else
        `ERR_ORDER_NOT_ALLOCATED`)"

        Design: Corner/endpoints/dispatch_empty_route_rejected
        """
        route = create_route()
        resp = api_client.dispatch_route(
            route["id"], {"expected_route_version": route["version"]}, FLEET)
        validate_error(resp, ApiErrorId.ERR_ROUTE_EMPTY)
        assert resp.status_code == 422
        after = get_route(route["id"])
        assert after["status"] == "PLAN"

    def test_close_route_with_open_stop_rejected(self):
        """PRD §3.8: "The close requires `DISPATCHED` status (else
        `ERR_ROUTE_NOT_DISPATCHED`) and every stop resolved to `COMPLETED` or
        `SKIPPED` (else `ERR_STOPS_OPEN`)"

        Design: Corner/validations/route_close_blocked_by_open_stops
        """
        spec, _lot, customer = setup_sellable_world("CloseBlock",
                                                    lot_quantity=100)
        order = create_allocated_order(customer["id"], spec["id"], 1)
        route = create_route()
        stop = add_route_stop(route["id"], 1, "DELIVERY", order_id=order["id"])
        dispatch_route_current_version(route["id"])
        arrive_stop(stop["id"])
        # Stop is ARRIVED — not yet COMPLETED or SKIPPED.
        resp = api_client.close_route(route["id"], {"fuel_surcharge_cents": 0},
                                      FLEET)
        validate_error(resp, ApiErrorId.ERR_STOPS_OPEN)
        assert resp.status_code == 409
        after = get_route(route["id"])
        assert after["status"] == "DISPATCHED"
