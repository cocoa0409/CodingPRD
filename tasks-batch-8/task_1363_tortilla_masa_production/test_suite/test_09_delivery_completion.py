"""Delivery, shorting, route/run completion gates, and the case-load
conservation invariant."""
from test_helpers import (
    ApiErrorId,
    assert_case_load,
    assert_route_stop,
    create_pack_order,
    create_route,
    get_route,
    setup_dispatched_route_with_stop,
    setup_in_progress_run,
    setup_route_with_stop,
    setup_sealed_pack,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

DISP = TEST_USERS["route_dispatcher_headers"]
SCHED = TEST_USERS["line_scheduler_headers"]
PACK = TEST_USERS["packaging_lead_headers"]


class TestDelivery:
    def test_delivery_with_shortage_records_delta_without_restock(self, api):
        """PRD §3.9: "Delivery sets `delivered_cases`, computes `shortage_cases`
        as `allocated_cases` minus `delivered_cases`, and advances the stop to
        terminal `DELIVERED`. A shortage recorded at delivery is **not**
        restocked — the route has already dispatched."
        Delivering 18 of 20: shortage 2, and the pack's cases_available stays 0.

        Design: Corner/endpoints/ep_deliver_with_shortage_records_delta
        """
        ctx = setup_dispatched_route_with_stop(
            requested_cases=20, cases_packed=20,
            product_overrides={"sku_code": "C-SH"},
            line_overrides={"line_code": "L-SH"},
            customer_overrides={"account_name": "SH Mart", "base_weekly_cases": 20},
            route_overrides={"route_code": "R-SH", "region": "R1"},
        )
        stop = validate_success(api.deliver_stop(ctx["stop"]["id"], 18, DISP))
        assert_route_stop(stop)
        assert stop["stop_status"] == "DELIVERED"
        assert stop["delivered_cases"] == 18
        assert stop["shortage_cases"] == 2
        pack = validate_success(api.get_pack_order(ctx["pack_order"]["id"], DISP))
        assert pack["cases_available"] == 0, "delivery shortage is not restocked"

    def test_deliver_twice_rejected(self, api):
        """PRD §3.9: "Delivering a stop requires it to be in `ALLOCATED` and the
        parent route to be `DISPATCHED`." A DELIVERED stop is terminal, so the
        second deliver fails the from-state check with ERR_STOP_INVALID_STATE
        (§5).

        Design: Corner/state_machines/sm_stop_deliver_twice_rejected
        """
        ctx = setup_dispatched_route_with_stop(
            requested_cases=10, cases_packed=10,
            product_overrides={"sku_code": "SM-SD"},
            line_overrides={"line_code": "L-SD"},
            customer_overrides={"account_name": "SD Mart", "base_weekly_cases": 10},
            route_overrides={"route_code": "R-SD", "region": "R1"},
        )
        validate_success(api.deliver_stop(ctx["stop"]["id"], 10, DISP))
        validate_error(
            api.deliver_stop(ctx["stop"]["id"], 10, DISP),
            ApiErrorId.ERR_STOP_INVALID_STATE,
        )

    def test_delivered_cases_above_allocated_rejected(self, api):
        """PRD §3.9: "The dispatcher supplies `delivered_cases`, which may not
        exceed `allocated_cases` — a larger value is rejected with
        `ERR_VALIDATION`."
        11 delivered against 10 allocated.

        Design: Corner/validations/val_delivered_cases_above_allocated
        """
        ctx = setup_dispatched_route_with_stop(
            requested_cases=10, cases_packed=10,
            product_overrides={"sku_code": "C-DV"},
            line_overrides={"line_code": "L-DV"},
            customer_overrides={"account_name": "DV Mart", "base_weekly_cases": 10},
            route_overrides={"route_code": "R-DV", "region": "R1"},
        )
        validate_error(
            api.deliver_stop(ctx["stop"]["id"], 11, DISP), ApiErrorId.ERR_VALIDATION
        )


class TestRouteDispatchAndCompletion:
    def test_dispatch_empty_route_rejected(self, api):
        """PRD §3.9: "Dispatching a route requires it to be in `PLANNED` and to
        have at least one stop in `ALLOCATED` — dispatching an empty route is
        rejected with `ERR_ROUTE_EMPTY`."

        Design: Corner/endpoints/ep_dispatch_empty_route_rejected
        """
        route = create_route(route_code="R-EMPTY", route_date="2026-08-05",
                             region="R1")
        validate_error(api.dispatch_route(route["id"], DISP), ApiErrorId.ERR_ROUTE_EMPTY)
        after = get_route(route["id"])
        assert after["route_status"] == "PLANNED"

    def test_complete_with_unresolved_stops_rejected(self, api):
        """PRD §3.9: "Completing a route requires it to be in `DISPATCHED` and
        every stop to be in a terminal state — `DELIVERED` or `SHORTED` —
        otherwise `ERR_UNRESOLVED_STOPS`."
        The stop is still ALLOCATED.

        Design: Corner/endpoints/ep_route_complete_with_unresolved_stops
        """
        ctx = setup_dispatched_route_with_stop(
            requested_cases=10, cases_packed=10,
            product_overrides={"sku_code": "C-US"},
            line_overrides={"line_code": "L-US"},
            customer_overrides={"account_name": "US Mart", "base_weekly_cases": 10},
            route_overrides={"route_code": "R-US", "region": "R1"},
        )
        validate_error(
            api.complete_route(ctx["route"]["id"], DISP),
            ApiErrorId.ERR_UNRESOLVED_STOPS,
        )
        after = get_route(ctx["route"]["id"])
        assert after["route_status"] == "DISPATCHED"

    def test_completed_route_accepts_no_further_transitions(self, api):
        """PRD §3.9: "Cancelling a route is permitted only from `PLANNED`" — a
        COMPLETED route fails the from-state check with ERR_ROUTE_INVALID_STATE
        (§5).

        Design: Corner/state_machines/sm_route_completed_terminal_lockdown
        """
        ctx = setup_dispatched_route_with_stop(
            requested_cases=5, cases_packed=5,
            product_overrides={"sku_code": "SM-RT"},
            line_overrides={"line_code": "L-RT"},
            customer_overrides={"account_name": "RT Mart", "base_weekly_cases": 10},
            route_overrides={"route_code": "R-RT", "region": "R1"},
        )
        validate_success(api.deliver_stop(ctx["stop"]["id"], 5, DISP))
        completed = validate_success(api.complete_route(ctx["route"]["id"], DISP))
        assert completed["route_status"] == "COMPLETED"
        validate_error(
            api.cancel_route(ctx["route"]["id"], DISP),
            ApiErrorId.ERR_ROUTE_INVALID_STATE,
        )


class TestRunCompletion:
    def test_complete_with_open_pack_orders_rejected(self, api):
        """PRD §3.5: "Every child `PackOrder` must be in a terminal state —
        `SEALED`, `REJECTED`, or `CANCELLED` — otherwise
        `ERR_UNRESOLVED_PACK_ORDERS`."
        The child pack order is still PACKING.

        Design: Corner/endpoints/ep_run_complete_with_open_pack_orders
        """
        ctx = setup_in_progress_run(
            planned_cases=50, allocated_kg=194.4,
            product_overrides={"sku_code": "C-UP"},
            line_overrides={"line_code": "L-UP"},
        )
        pack_order = create_pack_order(ctx["run"]["id"], cases_planned=50)
        validate_success(api.start_packing(pack_order["id"], PACK))
        validate_error(
            api.complete_run(ctx["run"]["id"], SCHED),
            ApiErrorId.ERR_UNRESOLVED_PACK_ORDERS,
        )
        run = validate_success(api.get_run(ctx["run"]["id"], SCHED))
        assert run["production_status"] == "IN_PROGRESS"

    def test_complete_below_attainment_rejected(self, api):
        """PRD §3.5: "`produced_cases` — the sum of `cases_packed` over the run's
        `SEALED` pack orders — must be at least `planned_cases` multiplied by 0.95
        and rounded up to a whole number; a shortfall is rejected with
        `ERR_RUN_CASE_SHORTFALL`."
        94 sealed against planned 100: ceil(100 x 0.95) = 95, so 94 fails.

        Design: Corner/endpoints/ep_run_complete_case_shortfall
        """
        ctx = setup_sealed_pack(
            cases_packed=94, planned_cases=100, allocated_kg=388.8,
            cases_planned=100,
            product_overrides={"sku_code": "C-SF"},
            line_overrides={"line_code": "L-SF", "cases_per_hour": 200},
        )
        validate_error(
            api.complete_run(ctx["run"]["id"], SCHED),
            ApiErrorId.ERR_RUN_CASE_SHORTFALL,
        )
        run = validate_success(api.get_run(ctx["run"]["id"], SCHED))
        assert run["production_status"] == "IN_PROGRESS"

    def test_complete_at_exact_attainment_boundary(self, api):
        """PRD §3.5: "`produced_cases` — the sum of `cases_packed` over the run's
        `SEALED` pack orders — must be at least `planned_cases` multiplied by 0.95
        and rounded up to a whole number; a shortfall is rejected with
        `ERR_RUN_CASE_SHORTFALL`. Completion finalizes `produced_cases` and
        advances the run to `COMPLETED`."
        95 sealed against planned 100: 95 >= ceil(100 x 0.95) = 95 (inclusive).

        Design: Corner/calculations/calc_run_completion_underfill_boundary
        """
        ctx = setup_sealed_pack(
            cases_packed=95, planned_cases=100, allocated_kg=388.8,
            cases_planned=100,
            product_overrides={"sku_code": "C-UF"},
            line_overrides={"line_code": "L-UF", "cases_per_hour": 200},
        )
        completed = validate_success(api.complete_run(ctx["run"]["id"], SCHED))
        assert completed["production_status"] == "COMPLETED"
        assert completed["produced_cases"] == 95


class TestCaseLoadConservation:
    def test_stop_creation_moves_cases_into_allocated(self, api):
        """PRD §2.10: "The **case load invariant** states that for any pack order,
        `cases_packed` always equals `cases_available` plus the sum of
        `allocated_cases` over route stops in `ALLOCATED` or `DELIVERED` that
        reference this pack." and "On the route side, `committed_cases` is the sum
        of `allocated_cases` over stops in `ALLOCATED` or `DELIVERED`".
        Stop of 30 from a 50-case pack: 50 == 20 + 30; route committed 30.

        Design: Difficulty/compensating_invariant/cases_stop_short_conserves_pack_cases
        """
        ctx = setup_route_with_stop(
            requested_cases=30, cases_packed=50, planned_cases=50,
            allocated_kg=194.4,
            product_overrides={"sku_code": "CORN-6-C2"},
            line_overrides={"line_code": "L-C2"},
            customer_overrides={"account_name": "Carniceria C2",
                                "channel": "TORTILLERIA", "priority_tier": "B",
                                "min_shelf_life_pct": 40},
            route_overrides={"route_code": "R-C2"},
        )
        pack = validate_success(api.get_pack_order(ctx["pack_order"]["id"], DISP))
        route = get_route(ctx["route"]["id"])
        assert pack["cases_available"] == 20
        assert route["committed_cases"] == 30
        assert_case_load(pack, 30)

    def test_short_returns_cases_and_refunds_route(self, api):
        """PRD §3.9: "Shorting advances the stop to terminal `SHORTED`, adds
        `allocated_cases` back to the pack's `cases_available`, subtracts
        `allocated_cases` from the route's `committed_cases`". The forward +
        compensating pair leaves the conserved total unchanged: 50 == 50 + 0 and
        committed returns to 0.

        Design: Difficulty/compensating_invariant/cases_stop_short_conserves_pack_cases
        """
        ctx = setup_route_with_stop(
            requested_cases=30, cases_packed=50, planned_cases=50,
            allocated_kg=194.4,
            product_overrides={"sku_code": "CORN-6-C2"},
            line_overrides={"line_code": "L-C2"},
            customer_overrides={"account_name": "Carniceria C2",
                                "channel": "TORTILLERIA", "priority_tier": "B",
                                "min_shelf_life_pct": 40},
            route_overrides={"route_code": "R-C2"},
        )
        shorted = validate_success(api.short_stop(ctx["stop"]["id"], DISP))
        assert shorted["stop_status"] == "SHORTED"
        pack = validate_success(api.get_pack_order(ctx["pack_order"]["id"], DISP))
        route = get_route(ctx["route"]["id"])
        assert pack["cases_available"] == 50
        assert route["committed_cases"] == 0
        assert_case_load(pack, 0)
