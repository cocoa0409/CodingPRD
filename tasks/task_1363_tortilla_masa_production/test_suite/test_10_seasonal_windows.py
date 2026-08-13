"""Seasonal windows: inclusive date overlap, activation waterfall, strict-mode
shorting sweep, allotment gate, and activation idempotency."""
from test_helpers import (
    ApiErrorId,
    assert_seasonal_window,
    create_customer,
    create_route,
    create_route_stop_payload,
    create_seasonal_window,
    create_seasonal_window_payload,
    create_stop,
    get_route,
    set_clock,
    setup_sealed_pack,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
DISP = TEST_USERS["route_dispatcher_headers"]


def _window_allotment_by_customer(api, customer_id):
    data, meta = validate_paginated(api.list_customer_allotments(customer_id, PM))
    assert meta["total_count"] == 1
    return data[0]


class TestWindowDateOverlap:
    def test_adjacent_window_accepted(self, api):
        """PRD §3.8: "Adjacency — one window's `ends_on` plus one day equal to the
        next's `starts_on` — is allowed; sharing even one calendar day is a
        conflict." and "A new window enters in `window_status` `SCHEDULED`, and
        `is_strict` computes to true when `demand_multiplier` is at least 1.5."
        W2 starts 2026-08-21, the day after W1's inclusive end 2026-08-20.

        Design: Difficulty/resource_temporal_overlap/seasonal_windows_inclusive_date_overlap
        """
        create_seasonal_window(window_name="W1", starts_on="2026-08-10",
                               ends_on="2026-08-20", demand_multiplier=1.2,
                               forecast_total_cases=100)
        w2 = create_seasonal_window(window_name="W2", starts_on="2026-08-21",
                                    ends_on="2026-08-25", demand_multiplier=1.2,
                                    forecast_total_cases=100)
        assert_seasonal_window(w2)
        assert w2["window_status"] == "SCHEDULED"
        assert w2["is_strict"] is False, "1.2 < 1.5 is not strict"

    def test_shared_calendar_day_rejected(self, api):
        """PRD §3.8: "Window dates form a **closed inclusive interval**
        `[starts_on, ends_on]` — both ends inclusive — which differs from the
        half-open semantics of line windows: two windows conflict when the
        first's `starts_on` is on or before the second's `ends_on` and the
        first's `ends_on` is on or after the second's `starts_on`." and "An
        overlap is rejected with `ERR_WINDOW_DATE_OVERLAP`."
        W3 [08-20, 08-22] shares 2026-08-20 with W1 [08-10, 08-20].

        Design: Difficulty/resource_temporal_overlap/seasonal_windows_inclusive_date_overlap
        """
        create_seasonal_window(window_name="W1", starts_on="2026-08-10",
                               ends_on="2026-08-20", demand_multiplier=1.2,
                               forecast_total_cases=100)
        validate_error(
            api.create_seasonal_window(
                create_seasonal_window_payload(
                    window_name="W3", starts_on="2026-08-20", ends_on="2026-08-22",
                    demand_multiplier=1.3, forecast_total_cases=100,
                ),
                PM,
            ),
            ApiErrorId.ERR_WINDOW_DATE_OVERLAP,
        )


class TestAllotmentWaterfall:
    def _activated_window_with_four_customers(self, api):
        fs = create_customer(account_name="FS Dist", channel="FOODSERVICE_DIST",
                             base_weekly_cases=100, priority_tier="A",
                             min_shelf_life_pct=30)
        ra = create_customer(account_name="Retail A", base_weekly_cases=200,
                             priority_tier="A", min_shelf_life_pct=50)
        rb = create_customer(account_name="Retail B", base_weekly_cases=300,
                             priority_tier="B", min_shelf_life_pct=50)
        rc = create_customer(account_name="Retail C", channel="TORTILLERIA",
                             base_weekly_cases=400, priority_tier="C",
                             min_shelf_life_pct=40)
        window = create_seasonal_window(window_name="CINCO_SURGE",
                                        starts_on="2026-08-10",
                                        ends_on="2026-08-16",
                                        demand_multiplier=1.5,
                                        forecast_total_cases=1000)
        set_clock("2026-08-10T08:00:00Z")
        activated = validate_success(api.activate_seasonal_window(window["id"], PM))
        return activated, {"fs": fs, "ra": ra, "rb": rb, "rc": rc}

    def test_foodservice_first_then_tier_a(self, api):
        """PRD §3.8: "A new window enters in `window_status` `SCHEDULED`, and
        `is_strict` computes to true when `demand_multiplier` is at least 1.5."
        and the waterfall: foodservice first (ceil(100 x 1.5) = 150), then the
        retail pool 1000 - 150 = 850 feeds tier A (min(ceil(200 x 1.5 x 1.0),
        850) = 300).

        Design: Difficulty/combinatorial_formula/seasonal_allotment_waterfall_evaluation_order
        """
        activated, customers = self._activated_window_with_four_customers(api)
        assert activated["window_status"] == "ACTIVE"
        assert activated["is_strict"] is True, "1.5 meets the strict threshold"
        fs_allotment = _window_allotment_by_customer(api, customers["fs"]["id"])
        ra_allotment = _window_allotment_by_customer(api, customers["ra"]["id"])
        assert fs_allotment["allotted_cases"] == 150
        assert ra_allotment["allotted_cases"] == 300

    def test_tier_b_then_c_partial_fill_exhausts_pool(self, api):
        """Waterfall (same PRD §3.8 steps): after foodservice (150) and tier A
        (300) the pool is 550; tier B is allotted min(ceil(300 x 1.5 x 0.8) =
        360, 550) = 360 leaving 190; tier C is allotted min(360, 190) = 190 — a
        partial fill that exactly exhausts the 1000-case forecast.

        Design: Difficulty/combinatorial_formula/seasonal_allotment_waterfall_evaluation_order
        """
        _, customers = self._activated_window_with_four_customers(api)
        rb_allotment = _window_allotment_by_customer(api, customers["rb"]["id"])
        rc_allotment = _window_allotment_by_customer(api, customers["rc"]["id"])
        assert rb_allotment["allotted_cases"] == 360
        assert rc_allotment["allotted_cases"] == 190
        total = 150 + 300 + rb_allotment["allotted_cases"] + rc_allotment["allotted_cases"]
        assert total == 1000, "allotments sum to the forecast pool"


class TestStrictWindowSweep:
    def _preexisting_stop_then_activate(self, api):
        """Sealed pack (20 cases) fully allocated to a stop on a route dated
        2026-08-12 BEFORE the window exists; then a strict window covering
        2026-08-10..16 is activated at clock 2026-08-10."""
        ctx = setup_sealed_pack(
            cases_packed=20, planned_cases=50, allocated_kg=194.4,
            product_overrides={"sku_code": "CORN-6-SW"},
            line_overrides={"line_code": "L-SW"},
        )
        customer = create_customer(account_name="Tienda D", base_weekly_cases=10,
                                   priority_tier="A", min_shelf_life_pct=40)
        route = create_route(route_code="R-SW", route_date="2026-08-12")
        stop = create_stop(route["id"], customer["id"], ctx["pack_order"]["id"],
                           requested_cases=20)
        window = create_seasonal_window(window_name="NAVIDAD",
                                        starts_on="2026-08-10",
                                        ends_on="2026-08-16",
                                        demand_multiplier=1.5,
                                        forecast_total_cases=500)
        set_clock("2026-08-10T08:00:00Z")
        return ctx, customer, route, stop, window

    def test_activation_shorts_stop_exceeding_new_allotment(self, api):
        """PRD §3.8: "For **strict** windows — those with `is_strict` true —
        activation additionally runs an enforcement sweep: pre-existing stops in
        `ALLOCATED` on routes dated inside the window that exceed the new
        allotment are shorted, processed in `created_at` ascending order, with
        each short atomic (no partial fills)."
        The customer's allotment is ceil(10 x 1.5 x 1.0) = 15; the pre-existing
        20-case stop exceeds it and shorts.

        Design: Difficulty/transitive_cascade/seasonal_activation_sweep_shortens_stops
        """
        _, customer, _, stop, window = self._preexisting_stop_then_activate(api)
        activated = validate_success(api.activate_seasonal_window(window["id"], PM))
        assert activated["window_status"] == "ACTIVE"
        allotment = _window_allotment_by_customer(api, customer["id"])
        assert allotment["allotted_cases"] == 15
        stop_after = validate_success(api.get_stop(stop["id"], DISP))
        assert stop_after["stop_status"] == "SHORTED"

    def test_sweep_restores_pack_and_refunds_route_and_allotment(self, api):
        """PRD §3.8: "Each shorted stop restores the pack's `cases_available`,
        refunds the route's `committed_cases`, and refunds the allotment's
        `consumed_cases`."
        The pack returns to 20 available, the route to 0 committed, and the
        allotment shows nothing consumed.

        Design: Difficulty/transitive_cascade/seasonal_activation_sweep_shortens_stops
        """
        ctx, customer, route, _stop, window = (
            self._preexisting_stop_then_activate(api)
        )
        validate_success(api.activate_seasonal_window(window["id"], PM))
        pack = validate_success(api.get_pack_order(ctx["pack_order"]["id"], DISP))
        assert pack["cases_available"] == 20
        route_after = get_route(route["id"])
        assert route_after["committed_cases"] == 0
        allotment = _window_allotment_by_customer(api, customer["id"])
        assert allotment["consumed_cases"] == 0


class TestWindowActivationState:
    def test_activate_twice_rejected_without_duplicating_allotments(self, api):
        """PRD §3.8: "Activating a window requires it to be in `SCHEDULED` and the
        logical clock's date to lie inside `[starts_on, ends_on]` — otherwise
        `ERR_WINDOW_INVALID_STATE`." The second activation fails and the single
        allotment from the first activation is not duplicated.

        Design: Corner/state_machines/sm_window_activate_twice_rejected
        """
        create_customer(account_name="WA", base_weekly_cases=10,
                        region="R1", min_shelf_life_pct=10)
        window = create_seasonal_window(window_name="W2X", starts_on="2026-08-10",
                                        ends_on="2026-08-16",
                                        demand_multiplier=1.2,
                                        forecast_total_cases=100)
        set_clock("2026-08-10T08:00:00Z")
        validate_success(api.activate_seasonal_window(window["id"], PM))
        validate_error(
            api.activate_seasonal_window(window["id"], PM),
            ApiErrorId.ERR_WINDOW_INVALID_STATE,
        )
        _, meta = validate_paginated(api.list_window_allotments(window["id"], PM))
        assert meta["total_count"] == 1


class TestAllotmentGate:
    def test_request_above_allotment_rejected(self, api):
        """PRD §3.9: "And when the route's `route_date` falls inside a strict
        seasonal window, the customer's allotment for that window must have
        `remaining_cases` at least `requested_cases` — otherwise
        `ERR_ALLOTMENT_EXCEEDED`."
        Allotment 15 (ceil(10 x 1.5)); capacity 100 and stock 50 are ample; the
        request for 20 fails the fiscal gate alone.

        Design: Corner/errors/err_allotment_exceeded_isolated
        """
        ctx = setup_sealed_pack(
            cases_packed=50, planned_cases=50, allocated_kg=194.4,
            product_overrides={"sku_code": "C-AE"},
            line_overrides={"line_code": "L-AE"},
        )
        customer = create_customer(account_name="AE Mart", base_weekly_cases=10,
                                   region="R1", min_shelf_life_pct=30)
        window = create_seasonal_window(window_name="W-AE", starts_on="2026-08-03",
                                        ends_on="2026-08-09",
                                        demand_multiplier=1.5,
                                        forecast_total_cases=500)
        set_clock("2026-08-03T08:00:00Z")
        validate_success(api.activate_seasonal_window(window["id"], PM))
        route = create_route(route_code="R-AE", route_date="2026-08-05", region="R1")
        validate_error(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(customer["id"], ctx["pack_order"]["id"],
                                          route["version"], requested_cases=20),
                DISP,
            ),
            ApiErrorId.ERR_ALLOTMENT_EXCEEDED,
        )
