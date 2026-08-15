"""Route stop creation gates: pack sealed state, shelf-life boundary, stock,
credit, OCC on route version, and validation priority between competing
failures."""
from test_helpers import (
    ApiErrorId,
    create_customer,
    create_pack_order,
    create_route,
    create_route_stop_payload,
    create_seasonal_window,
    create_stop,
    get_route,
    pack_order_pass_weight_check,
    seal_pack_order,
    set_clock,
    setup_in_progress_run,
    setup_sealed_pack,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
DISP = TEST_USERS["route_dispatcher_headers"]
PACK = TEST_USERS["packaging_lead_headers"]


class TestStopRequiresSealedPack:
    def test_stop_against_unsealed_pack_rejected(self, api):
        """PRD §3.9: "The referenced pack order must be `SEALED` — otherwise
        `ERR_PACK_NOT_SEALED`." The pack order is PASSED (weight check complete)
        but not yet sealed, so stop creation fails; the rejection is no mutation,
        so the route version is unchanged (PRD §2.4: "`version` (an integer that
        increments on every mutation of that entity)").

        Design: Difficulty/cross_entity_state_dependency/stop_blocked_until_pack_sealed
        """
        ctx = setup_in_progress_run(
            planned_cases=50, allocated_kg=194.4,
            product_overrides={"sku_code": "CORN-6-X2"},
            line_overrides={"line_code": "L-X2"},
        )
        pack_order = create_pack_order(ctx["run"]["id"], cases_planned=20)
        pack_order_pass_weight_check(pack_order["id"], 20)
        customer = create_customer(account_name="Mercado X2", min_shelf_life_pct=50)
        route = create_route(route_code="R-X2", route_date="2026-08-05")
        version_before = route["version"]
        validate_error(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(customer["id"], pack_order["id"],
                                          version_before, requested_cases=5),
                DISP,
            ),
            ApiErrorId.ERR_PACK_NOT_SEALED,
        )
        after = get_route(route["id"])
        assert after["version"] == version_before, "rejection must not bump version"

    def test_stop_succeeds_after_seal(self, api):
        """PRD §3.9: "The referenced pack order must be `SEALED` — otherwise
        `ERR_PACK_NOT_SEALED`." and "When every gate passes, allocation is
        **atomic**: `allocated_cases` equals `requested_cases` with no partial
        fills." After sealing, the identical request allocates fully.

        Design: Difficulty/cross_entity_state_dependency/stop_blocked_until_pack_sealed
        """
        ctx = setup_in_progress_run(
            planned_cases=50, allocated_kg=194.4,
            product_overrides={"sku_code": "CORN-6-X2"},
            line_overrides={"line_code": "L-X2"},
        )
        pack_order = create_pack_order(ctx["run"]["id"], cases_planned=20)
        pack_order_pass_weight_check(pack_order["id"], 20)
        customer = create_customer(account_name="Mercado X2", min_shelf_life_pct=50)
        route = create_route(route_code="R-X2", route_date="2026-08-05")
        seal_pack_order(pack_order["id"])
        stop = create_stop(route["id"], customer["id"], pack_order["id"],
                           requested_cases=5)
        assert stop["stop_status"] == "ALLOCATED"
        assert stop["allocated_cases"] == 5


class TestShelfLifeGate:
    def test_exact_threshold_allocates(self, api):
        """PRD §3.9: "The shelf-life gate then applies: `remaining_days` is the
        whole-day difference between the pack's `expires_on` and the route's
        `route_date`, and the gate passes when `remaining_days` multiplied by 100
        is at least the customer's `min_shelf_life_pct` multiplied by the
        product's `shelf_life_days`; the comparison is integer arithmetic and
        inclusive at the exact boundary — violation yields
        `ERR_SHELF_LIFE_INSUFFICIENT`."
        Sealed 2026-08-01 with a 20-day shelf life -> expires_on 2026-08-21; route
        date 2026-08-11 leaves exactly 10 days: 10 x 100 == 50 x 20 -> passes.

        Design: Difficulty/boundary_precision_check/shelf_life_exact_threshold_passes
        """
        ctx = setup_sealed_pack(
            cases_packed=20, planned_cases=50, allocated_kg=194.4,
            product_overrides={"sku_code": "CORN-6-B2"},
            line_overrides={"line_code": "L-B2"},
        )
        assert ctx["pack_order"]["expires_on"] == "2026-08-21"
        customer = create_customer(account_name="Supermercado Sol",
                                   min_shelf_life_pct=50)
        route = create_route(route_code="R-B2", route_date="2026-08-11")
        stop = create_stop(route["id"], customer["id"], ctx["pack_order"]["id"],
                           requested_cases=20)
        assert stop["stop_status"] == "ALLOCATED"
        assert stop["allocated_cases"] == 20

    def test_one_day_below_threshold_rejected(self, api):
        """PRD §3.9: "the gate passes when `remaining_days` multiplied by 100 is
        at least the customer's `min_shelf_life_pct` multiplied by the product's
        `shelf_life_days`; the comparison is integer arithmetic and inclusive at
        the exact boundary — violation yields `ERR_SHELF_LIFE_INSUFFICIENT`."
        Route date 2026-08-12 leaves 9 days: 9 x 100 = 900 < 50 x 20 = 1000.

        Design: Difficulty/boundary_precision_check/shelf_life_exact_threshold_passes
        """
        ctx = setup_sealed_pack(
            cases_packed=20, planned_cases=50, allocated_kg=194.4,
            product_overrides={"sku_code": "CORN-6-B2"},
            line_overrides={"line_code": "L-B2"},
        )
        customer = create_customer(account_name="Supermercado Sol",
                                   min_shelf_life_pct=50)
        route = create_route(route_code="R-B2L", route_date="2026-08-12")
        validate_error(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(customer["id"], ctx["pack_order"]["id"],
                                          route["version"], requested_cases=20),
                DISP,
            ),
            ApiErrorId.ERR_SHELF_LIFE_INSUFFICIENT,
        )

    def test_below_threshold_persists_no_stop(self, api):
        """PRD §3.9: "the gate passes when `remaining_days` multiplied by 100 is
        at least the customer's `min_shelf_life_pct` multiplied by the product's
        `shelf_life_days`; the comparison is integer arithmetic and inclusive at
        the exact boundary — violation yields `ERR_SHELF_LIFE_INSUFFICIENT`."
        The rejected request allocates nothing: committed_cases stays zero and no
        stop is listed on the route.

        Design: Corner/calculations/calc_shelf_life_below_threshold_fails
        """
        ctx = setup_sealed_pack(
            cases_packed=10, planned_cases=50, allocated_kg=194.4,
            product_overrides={"sku_code": "C-SL"},
            line_overrides={"line_code": "L-SL"},
        )
        customer = create_customer(account_name="SL Mart", min_shelf_life_pct=50)
        route = create_route(route_code="R-SL", route_date="2026-08-12", region="R1")
        validate_error(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(customer["id"], ctx["pack_order"]["id"],
                                          route["version"], requested_cases=5),
                DISP,
            ),
            ApiErrorId.ERR_SHELF_LIFE_INSUFFICIENT,
        )
        route_after = get_route(route["id"])
        assert route_after["committed_cases"] == 0
        _, meta = validate_paginated(api.list_route_stops(route["id"], DISP))
        assert meta["total_count"] == 0


class TestStockAndCreditGates:
    def test_pack_stock_insufficient(self, api):
        """PRD §3.9: "The pack must have enough stock — `cases_available` at least
        `requested_cases`, otherwise `ERR_PACK_STOCK_INSUFFICIENT`."
        Requesting 11 from a pack holding 10 with ample route capacity.

        Design: Corner/errors/err_pack_stock_insufficient
        """
        ctx = setup_sealed_pack(
            cases_packed=10, planned_cases=50, allocated_kg=194.4,
            product_overrides={"sku_code": "C-PS"},
            line_overrides={"line_code": "L-PS"},
        )
        customer = create_customer(account_name="PS Mart")
        route = create_route(route_code="R-PS", route_date="2026-08-05", region="R1")
        validate_error(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(customer["id"], ctx["pack_order"]["id"],
                                          route["version"], requested_cases=11),
                DISP,
            ),
            ApiErrorId.ERR_PACK_STOCK_INSUFFICIENT,
        )

    def test_credit_hold_blocks_stop(self, api):
        """PRD §3.8: "a customer on `HOLD` is blocked from receiving new stop
        allocations with `ERR_CUSTOMER_CREDIT_HOLD`." Every other gate passes:
        route PLANNED, pack SEALED with stock, shelf life ample, no window.

        Design: Corner/validations/val_credit_hold_blocks_stop
        """
        ctx = setup_sealed_pack(
            cases_packed=10, planned_cases=50, allocated_kg=194.4,
            product_overrides={"sku_code": "C-CH"},
            line_overrides={"line_code": "L-CH"},
        )
        customer = create_customer(account_name="CH Mart")
        validate_success(api.set_credit_standing(customer["id"], "HOLD", PM))
        route = create_route(route_code="R-CH", route_date="2026-08-05", region="R1")
        validate_error(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(customer["id"], ctx["pack_order"]["id"],
                                          route["version"], requested_cases=5),
                DISP,
            ),
            ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD,
        )


class TestStopCreateOcc:
    def test_stale_route_version_returns_412(self, api):
        """PRD §2.6: "Adding a route stop requires `expected_route_version` as a
        non-optional input field carrying the client's last observed `version` of
        the parent `Route`. If the route's current `version` has advanced since
        the client last read it — because a prior stop creation legitimately
        advanced it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412),
        preventing the client from allocating against a stale view of route
        capacity." PRD §3.9: "the route's `committed_cases` rises by
        `requested_cases` and the route's `version` increments by one".
        Stop 1 bumped the route version; replaying the stale snapshot fails.

        Design: Corner/cross_cutting_layers/cc_occ_stale_route_version_returns_412
        """
        ctx = setup_sealed_pack(
            cases_packed=30, planned_cases=50, allocated_kg=194.4,
            product_overrides={"sku_code": "C-OCC2"},
            line_overrides={"line_code": "L-OCC2"},
        )
        customer = create_customer(account_name="OCC2 Mart", base_weekly_cases=30)
        route = create_route(route_code="R-OCC2", route_date="2026-08-05", region="R1")
        stale_v = route["version"]
        create_stop(route["id"], customer["id"], ctx["pack_order"]["id"],
                    expected_route_version=stale_v, requested_cases=5)
        validate_error(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(customer["id"], ctx["pack_order"]["id"],
                                          stale_v, requested_cases=5),
                DISP,
            ),
            ApiErrorId.ERR_STALE_VERSION,
        )
        after = get_route(route["id"])
        assert after["version"] == stale_v + 1
        assert after["committed_cases"] == 5
        _, meta = validate_paginated(api.list_route_stops(route["id"], DISP))
        assert meta["total_count"] == 1


def _dispatched_route_with_hold_customer(api):
    """Sealed pack (20 cases), a customer moved GOOD -> HOLD after a first stop
    was allocated, and the route then DISPATCHED — a second stop create violates
    both the route state rule and the credit rule."""
    ctx = setup_sealed_pack(
        cases_packed=20, planned_cases=50, allocated_kg=194.4,
        product_overrides={"sku_code": "CORN-6-P1"},
        line_overrides={"line_code": "L-P1"},
    )
    customer = create_customer(account_name="HoldMart", min_shelf_life_pct=40)
    route = create_route(route_code="R-P1", route_date="2026-08-05")
    create_stop(route["id"], customer["id"], ctx["pack_order"]["id"],
                requested_cases=10)
    validate_success(api.set_credit_standing(customer["id"], "HOLD", PM))
    validate_success(api.dispatch_route(route["id"], DISP))
    return ctx, customer, get_route(route["id"])


class TestStateBeatsFiscalPriority:
    def test_dispatched_route_and_hold_customer_reports_state_error(self, api):
        """PRD §2.9: "When a request triggers multiple validations, they are
        evaluated in a fixed priority order, and the first failure surfaces its
        error; later failures are masked." with "5. State — OCC stale-version
        checks and target-entity from-state checks (`ERR_STALE_VERSION`,
        `ERR_BATCH_INVALID_STATE`, `ERR_LOT_INVALID_STATE`,
        `ERR_RUN_INVALID_STATE`, `ERR_ALLOCATION_INVALID_STATE`,
        `ERR_CHANGEOVER_INVALID_STATE`, `ERR_PACK_INVALID_STATE`,
        `ERR_PACK_NOT_SEALED`, `ERR_ROUTE_INVALID_STATE`, `ERR_STOP_INVALID_STATE`,
        `ERR_WINDOW_INVALID_STATE`, `ERR_PRODUCT_DISCONTINUED`)." listed ahead of
        "9. Business fiscal — customer credit and seasonal allotment
        (`ERR_CUSTOMER_CREDIT_HOLD`, `ERR_ALLOTMENT_EXCEEDED`)."
        Route DISPATCHED and customer on HOLD: ERR_ROUTE_INVALID_STATE surfaces.

        Design: Difficulty/priority_pair_validation_conflict/stop_create_state_beats_business_fiscal
        """
        ctx, customer, route = _dispatched_route_with_hold_customer(api)
        resp = api.create_route_stop(
            route["id"],
            create_route_stop_payload(customer["id"], ctx["pack_order"]["id"],
                                      route["version"], requested_cases=5),
            DISP,
        )
        err = validate_error(resp, ApiErrorId.ERR_ROUTE_INVALID_STATE)
        assert err["error_id"] != ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD

    def test_masked_fiscal_failure_allocates_nothing(self, api):
        """PRD §2.9: "the first failure surfaces its error; later failures are
        masked." The rejected request is no mutation: committed_cases stays at the
        first stop's 10 and the route version does not move (PRD §2.4: "`version`
        (an integer that increments on every mutation of that entity)").

        Design: Difficulty/priority_pair_validation_conflict/stop_create_state_beats_business_fiscal
        """
        ctx, customer, route = _dispatched_route_with_hold_customer(api)
        validate_error(
            api.create_route_stop(
                route["id"],
                create_route_stop_payload(customer["id"], ctx["pack_order"]["id"],
                                          route["version"], requested_cases=5),
                DISP,
            ),
            ApiErrorId.ERR_ROUTE_INVALID_STATE,
        )
        after = get_route(route["id"])
        assert after["committed_cases"] == 10
        assert after["version"] == route["version"]


def _strict_window_with_consumed_allotment(api):
    """Strict ACTIVE window (multiplier 1.5, forecast 500, 2026-08-10..16) whose
    tier-A customer (base 33 -> allotment 50) already consumed 10 cases on route
    1; returns ctx plus a second route (capacity 40) dated inside the window."""
    ctx = setup_sealed_pack(
        cases_packed=100, planned_cases=100, allocated_kg=388.8,
        product_overrides={"sku_code": "CORN-6-P3"},
        line_overrides={"line_code": "L-P3", "cases_per_hour": 200},
    )
    customer = create_customer(account_name="Capricornio", base_weekly_cases=33,
                               priority_tier="A", min_shelf_life_pct=30)
    window = create_seasonal_window(window_name="FIESTA", starts_on="2026-08-10",
                                    ends_on="2026-08-16", demand_multiplier=1.5,
                                    forecast_total_cases=500)
    set_clock("2026-08-10T08:00:00Z")
    validate_success(api.activate_seasonal_window(window["id"], PM))
    route1 = create_route(route_code="R-P3A", route_date="2026-08-12")
    create_stop(route1["id"], customer["id"], ctx["pack_order"]["id"],
                requested_cases=10)
    route2 = create_route(route_code="R-P3B", route_date="2026-08-12",
                          vehicle_capacity_cases=40)
    return ctx, customer, window, route1, route2


class TestConstraintBeatsFiscalPriority:
    def test_route_capacity_error_beats_allotment_error(self, api):
        """PRD §2.9: "the first failure surfaces its error; later failures are
        masked." with "8. Business constraint — masa, line capacity, route
        capacity, pack stock, weight-check sample, code uniqueness
        (`ERR_MASA_INSUFFICIENT`, `ERR_LINE_CAPACITY_EXCEEDED`,
        `ERR_ROUTE_CAPACITY_EXCEEDED`, `ERR_PACK_STOCK_INSUFFICIENT`,
        `ERR_WEIGHT_SAMPLE_INVALID`, `ERR_DUPLICATE_CODE`)." listed ahead of
        "9. Business fiscal — customer credit and seasonal allotment
        (`ERR_CUSTOMER_CREDIT_HOLD`, `ERR_ALLOTMENT_EXCEEDED`)."
        Requesting 45 violates both open_cases (40) and allotment remaining (40):
        the capacity error surfaces.

        Design: Difficulty/priority_pair_validation_conflict/stop_create_constraint_beats_business_fiscal
        """
        ctx, customer, _, _, route2 = _strict_window_with_consumed_allotment(api)
        resp = api.create_route_stop(
            route2["id"],
            create_route_stop_payload(customer["id"], ctx["pack_order"]["id"],
                                      route2["version"], requested_cases=45),
            DISP,
        )
        err = validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED)
        assert err["error_id"] != ApiErrorId.ERR_ALLOTMENT_EXCEEDED

    def test_masked_allotment_failure_allocates_nothing(self, api):
        """PRD §2.9: "the first failure surfaces its error; later failures are
        masked." The rejected stop allocates nothing: route2's open_cases stays
        40 (PRD §3.9: "`open_cases` at least `requested_cases`, otherwise
        `ERR_ROUTE_CAPACITY_EXCEEDED`").

        Design: Difficulty/priority_pair_validation_conflict/stop_create_constraint_beats_business_fiscal
        """
        ctx, customer, _, _, route2 = _strict_window_with_consumed_allotment(api)
        validate_error(
            api.create_route_stop(
                route2["id"],
                create_route_stop_payload(customer["id"], ctx["pack_order"]["id"],
                                          route2["version"], requested_cases=45),
                DISP,
            ),
            ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED,
        )
        after = get_route(route2["id"])
        assert after["open_cases"] == 40
        assert after["committed_cases"] == 0
        _, meta = validate_paginated(api.list_route_stops(route2["id"], DISP))
        assert meta["total_count"] == 0
