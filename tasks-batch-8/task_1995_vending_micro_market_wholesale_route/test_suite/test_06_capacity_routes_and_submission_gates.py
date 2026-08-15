"""Route capacity accounting (firm vs optimistic) and submit-time gates."""
from test_helpers import (
    ADMIN,
    PLANNER,
    ApiErrorId,
    activate_planogram,
    confirm_order,
    create_draft_planogram,
    create_location,
    create_operator,
    create_order,
    create_product,
    create_route,
    get_order,
    make_operator_manager_headers,
    setup_selling_location,
    submit_order,
    validate_error,
    validate_success,
)

DELIVERY_MONDAY = "2026-08-03"


class TestFirmVsOptimisticCapacity:
    def _capacity_world(self, api):
        """One CONFIRMED 6-case order and one SUBMITTED 4-case order on a
        capacity-10 route, both for the same delivery date."""
        world = setup_selling_location(
            products_spec=[{"sku": "CAP-1", "name": "Cap item",
                            "case_pack_qty": 1, "base_price_cents": 500,
                            "cost_cents": 300}],
            slots_spec=[{"slot_code": "A1", "product_index": 0,
                         "par_level_units": 10, "vend_price_cents": 100}],
            route_code="R-CAP",
            daily_case_capacity=10,
        )
        product = world["products"][0]
        order_a = create_order(
            world, [{"product_id": product["id"], "quantity_cases": 6}],
        )
        submit_order(world, order_a["id"])
        confirm_order(order_a["id"])
        order_b = create_order(
            world, [{"product_id": product["id"], "quantity_cases": 4}],
        )
        submit_order(world, order_b["id"])
        return world

    def test_availability_firm_counts_confirmed_only(self, api):
        """PRD §2.9: "The **firm** view sums `total_cases` over the orders for
        that route and date whose `fulfillment_status` is `CONFIRMED`." and
        "Remaining capacity is `daily_case_capacity` minus the consumed figure
        of the chosen variant"

        Design: Difficulty/dual_variant_calc/route_capacity_firm_vs_optimistic
        """
        world = self._capacity_world(api)
        data = validate_success(
            api.get_route_availability(world["route"]["id"], DELIVERY_MONDAY,
                                       ADMIN),
            200,
        )
        assert data["daily_case_capacity"] == 10
        assert data["firm_consumed_cases"] == 6
        assert data["firm_remaining_cases"] == 4

    def test_availability_optimistic_counts_submitted_too(self, api):
        """PRD §2.9: "The **optimistic** view sums `total_cases` over the
        orders whose `fulfillment_status` is `SUBMITTED` or `CONFIRMED`. For
        any route-date, the optimistic consumption is therefore at least the
        firm consumption, and strictly greater whenever at least one
        `SUBMITTED` order exists for that date."

        Design: Difficulty/dual_variant_calc/route_capacity_firm_vs_optimistic
        """
        world = self._capacity_world(api)
        data = validate_success(
            api.get_route_availability(world["route"]["id"], DELIVERY_MONDAY,
                                       ADMIN),
            200,
        )
        assert data["optimistic_consumed_cases"] == 10
        assert data["optimistic_remaining_cases"] == 0
        assert data["optimistic_consumed_cases"] != data["firm_consumed_cases"]


class TestRouteDayCapacityAggregate:
    def _aggregate_world(self, api):
        """Capacity-5 route with submitted orders of 3, 2, and 1 cases; the
        3-case order is already CONFIRMED."""
        world = setup_selling_location(
            products_spec=[{"sku": "CAGG-1", "name": "Cap agg item",
                            "case_pack_qty": 1, "base_price_cents": 500,
                            "cost_cents": 300}],
            slots_spec=[{"slot_code": "A1", "product_index": 0,
                         "par_level_units": 20, "vend_price_cents": 100}],
            route_code="R-CAGG",
            daily_case_capacity=5,
        )
        product = world["products"][0]
        orders = []
        for cases in (3, 2, 1):
            order = create_order(
                world, [{"product_id": product["id"], "quantity_cases": cases}],
            )
            submit_order(world, order["id"])
            orders.append(order)
        confirm_order(orders[0]["id"])  # firm consumption 3
        return world, orders

    def test_confirm_at_exact_capacity_passes(self, api):
        """PRD §2.9: "The confirmation gate uses the firm view: an order may be
        confirmed only when the firm consumption for its route and
        `requested_delivery_date` plus the order's own `total_cases` is less
        than or equal to the route's `daily_case_capacity`. Exact equality
        passes"

        Design: Difficulty/resource_temporal_overlap/route_day_capacity_aggregate
        """
        world, orders = self._aggregate_world(api)
        # 3 + 2 = 5 <= 5: exact equality passes.
        confirmed = confirm_order(orders[1]["id"])
        assert confirmed["fulfillment_status"] == "CONFIRMED"

    def test_confirm_beyond_capacity_rejected(self, api):
        """PRD §2.9: "Exact equality passes; anything beyond it rejects with
        `ERR_ROUTE_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/route_day_capacity_aggregate
        """
        world, orders = self._aggregate_world(api)
        confirm_order(orders[1]["id"])  # firm now 5
        # 5 + 1 = 6 > 5.
        err = api.confirm_order(orders[2]["id"], PLANNER)
        validate_error(err, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED)
        assert get_order(orders[2]["id"])["fulfillment_status"] == "SUBMITTED"


class TestConfirmCancelConservation:
    def _conservation_world(self, api):
        world = setup_selling_location(
            products_spec=[{"sku": "INV-1", "name": "Inv1 item",
                            "case_pack_qty": 1, "base_price_cents": 500,
                            "cost_cents": 300}],
            slots_spec=[{"slot_code": "A1", "product_index": 0,
                         "par_level_units": 20, "vend_price_cents": 100}],
            route_code="R-INV1",
            daily_case_capacity=10,
        )
        order = create_order(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 4}],
        )
        submit_order(world, order["id"])
        return world, order

    def test_confirm_raises_firm_consumption(self, api):
        """PRD §3.6: "On success the firm consumption for that route-date rises
        by the order's `total_cases` and the order's `version` increments."

        Design: Difficulty/compensating_invariant/confirm_cancel_capacity_conservation
        """
        world, order = self._conservation_world(api)
        confirm_order(order["id"])
        data = validate_success(
            api.get_route_availability(world["route"]["id"], DELIVERY_MONDAY,
                                       ADMIN),
            200,
        )
        assert data["firm_consumed_cases"] == 4

    def test_cancel_restores_firm_consumption(self, api):
        """PRD §2.9: "Cancelling a `CONFIRMED` order is the compensating action
        — it releases exactly that order's `total_cases` from the firm
        aggregate, restoring the pre-confirmation value"

        Design: Difficulty/compensating_invariant/confirm_cancel_capacity_conservation
        """
        world, order = self._conservation_world(api)
        confirm_order(order["id"])
        cancelled = validate_success(
            api.cancel_order(order["id"], world["om_headers"]), 200,
        )
        assert cancelled["fulfillment_status"] == "CANCELLED"
        data = validate_success(
            api.get_route_availability(world["route"]["id"], DELIVERY_MONDAY,
                                       ADMIN),
            200,
        )
        assert data["firm_consumed_cases"] == 0, (
            "confirm + cancel conserves firm capacity with no drift"
        )


class TestSubmitTemporalGates:
    def test_submit_delivery_date_temporal_gates(self, api):
        """PRD §3.5: "the temporal window (the `requested_delivery_date`
        strictly after the current logical date, else
        `ERR_DELIVERY_DATE_NOT_FUTURE`, and its weekday among the route's
        `delivery_weekdays`, else `ERR_DELIVERY_DAY_NOT_SERVED`)"
        PRD §2.5: "a date equal to that current date fails the rule."

        Design: Corner/errors/submit_delivery_date_temporal_gates
        """
        op = create_operator("Op Temp")
        route_sat = create_route("R-SAT", ("SAT",), 50, 0)
        route_mon = create_route("R-MON2", ("MON",), 50, 0)
        product = create_product(sku="TMP-1", name="Temp item")
        om = make_operator_manager_headers(op["id"])

        def _ready_location(route, name):
            loc = create_location(op["id"], route["id"], name)
            pg = create_draft_planogram(
                loc["id"],
                [{"slot_code": "A1", "product_id": product["id"],
                  "par_level_units": 10, "vend_price_cents": 150}],
                op["id"], "PG-" + name,
            )
            activate_planogram(pg["id"], loc["id"], op["id"])
            return loc

        loc_sat = _ready_location(route_sat, "L-Sat")
        loc_mon = _ready_location(route_mon, "L-Mon")

        # 2026-08-01 equals the current logical date (a Saturday, which the
        # route serves) — isolating the strictly-future gate.
        order_sat = validate_success(
            api.create_order(
                {"location_id": loc_sat["id"],
                 "requested_delivery_date": "2026-08-01",
                 "lines": [{"product_id": product["id"], "quantity_cases": 1}]},
                om,
            ),
            201,
        )
        err_s = api.submit_order(order_sat["id"], om)
        validate_error(err_s, ApiErrorId.ERR_DELIVERY_DATE_NOT_FUTURE)

        # 2026-08-04 is a future Tuesday on a MON-only route.
        order_mon = validate_success(
            api.create_order(
                {"location_id": loc_mon["id"],
                 "requested_delivery_date": "2026-08-04",
                 "lines": [{"product_id": product["id"], "quantity_cases": 1}]},
                om,
            ),
            201,
        )
        err_m = api.submit_order(order_mon["id"], om)
        validate_error(err_m, ApiErrorId.ERR_DELIVERY_DAY_NOT_SERVED)


class TestOperatorStatusGate:
    def _gate_world(self, api, sku="GTE-1", route_code="R-GTE"):
        world = setup_selling_location(
            products_spec=[{"sku": sku, "name": "Gate item",
                            "category": "BEVERAGE"}],
            route_code=route_code,
        )
        order = create_order(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 2}],
        )
        return world, order

    def test_submit_blocked_while_suspended(self, api):
        """PRD §2.8: "the operator must be `ACTIVE` for order submission, order
        confirmation, and service-ticket scheduling
        (`ERR_OPERATOR_NOT_ACTIVE`)"
        PRD §3.1: "the related-entity gates of §2.8 block new order
        submissions, order confirmations, credit-claim filings, and
        service-ticket scheduling for the suspended operator."

        Design: Difficulty/cross_entity_state_dependency/order_submit_gated_by_operator_status
        """
        world, order = self._gate_world(api)
        validate_success(api.suspend_operator(world["operator"]["id"], ADMIN), 200)
        err = api.submit_order(order["id"], world["om_headers"])
        validate_error(err, ApiErrorId.ERR_OPERATOR_NOT_ACTIVE)
        assert get_order(order["id"])["fulfillment_status"] == "DRAFT"

    def test_submit_reenabled_after_reinstate(self, api):
        """PRD §3.1: "Reinstatement moves `SUSPENDED` → `ACTIVE` under the same
        guard, and the cycle may loop indefinitely."
        PRD §3.1: "Suspension mutates no child rows — existing orders,
        planograms, claims, and tickets are left untouched"

        Design: Difficulty/cross_entity_state_dependency/order_submit_gated_by_operator_status
        """
        world, order = self._gate_world(api)
        validate_success(api.suspend_operator(world["operator"]["id"], ADMIN), 200)
        validate_error(
            api.submit_order(order["id"], world["om_headers"]),
            ApiErrorId.ERR_OPERATOR_NOT_ACTIVE,
        )
        validate_success(api.reinstate_operator(world["operator"]["id"], ADMIN), 200)
        submitted = validate_success(
            api.submit_order(order["id"], world["om_headers"]), 200,
        )
        assert submitted["fulfillment_status"] == "SUBMITTED"
        assert submitted["order_total_cents"] == 2000


class TestSubmitPriorityPair:
    def _priority_world(self, api):
        world = setup_selling_location(
            products_spec=[{"sku": "PR1-1", "name": "Prio item"}],
            route_code="R-PR1",
            min_order_cents=5000,
        )
        order = create_order(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 1}],
        )
        return world, order

    def test_suspended_submit_reports_operator_error(self, api):
        """PRD §2.8: "When a request would violate several rules, the
        violations are not reported together: the cascade below is evaluated in
        order, the first failing tier determines the response, and later tiers
        are never reached for that request." (tier 8 related-entity gates
        precede tier 12 fiscal gates.)
        PRD §2.8: "the operator must be `ACTIVE` for order submission, order
        confirmation, and service-ticket scheduling
        (`ERR_OPERATOR_NOT_ACTIVE`)"

        Design: Difficulty/priority_pair_validation_conflict/submit_suspended_operator_beats_min_order
        """
        world, order = self._priority_world(api)
        # Order total 1000 is also under the 5000 route minimum.
        validate_success(api.suspend_operator(world["operator"]["id"], ADMIN), 200)
        err = api.submit_order(order["id"], world["om_headers"])
        validate_error(err, ApiErrorId.ERR_OPERATOR_NOT_ACTIVE)
        assert get_order(order["id"])["fulfillment_status"] == "DRAFT"

    def test_min_order_error_surfaces_after_reinstate(self, api):
        """PRD §2.8: "the first failing tier determines the response" — with
        the tier-8 suspension lifted, the same submit reaches tier 12:
        "**Fiscal gates** (HTTP 422): `ERR_MIN_ORDER_NOT_MET` at order
        submission and `ERR_INSUFFICIENT_CREDIT_BALANCE` when applying credit."

        Design: Difficulty/priority_pair_validation_conflict/submit_suspended_operator_beats_min_order
        """
        world, order = self._priority_world(api)
        validate_success(api.suspend_operator(world["operator"]["id"], ADMIN), 200)
        validate_error(
            api.submit_order(order["id"], world["om_headers"]),
            ApiErrorId.ERR_OPERATOR_NOT_ACTIVE,
        )
        validate_success(api.reinstate_operator(world["operator"]["id"], ADMIN), 200)
        err = api.submit_order(order["id"], world["om_headers"])
        validate_error(err, ApiErrorId.ERR_MIN_ORDER_NOT_MET)
        assert get_order(order["id"])["fulfillment_status"] == "DRAFT"


class TestSubmitReferentialGates:
    def test_submit_product_not_on_planogram_rejected(self, api):
        """PRD §3.5: "present on the location's `ACTIVE` planogram, else
        `ERR_PRODUCT_NOT_ON_PLANOGRAM`"

        Design: Corner/errors/submit_product_not_on_planogram_rejected
        """
        world = setup_selling_location(
            products_spec=[{"sku": "NP-1", "name": "On planogram"}],
            route_code="R-NPL",
        )
        off_planogram = create_product(sku="NP-2", name="Off planogram",
                                       category="CANDY", base_price_cents=700,
                                       cost_cents=400, shelf_life_days=120)
        order = create_order(
            world,
            [{"product_id": off_planogram["id"], "quantity_cases": 1}],
        )
        err = api.submit_order(order["id"], world["om_headers"])
        validate_error(err, ApiErrorId.ERR_PRODUCT_NOT_ON_PLANOGRAM)

    def test_submit_with_discontinued_product_rejected(self, api):
        """PRD §3.2: "Discontinuation is never retroactive: orders already
        `SUBMITTED` or further along keep their pinned prices, while any future
        submission referencing the product fails with
        `ERR_PRODUCT_DISCONTINUED` at the referenced-entity-state tier."

        Design: Corner/errors/submit_with_discontinued_product_rejected
        """
        world = setup_selling_location(
            products_spec=[{"sku": "PD-1", "name": "Disc item"}],
            route_code="R-DISC",
        )
        order = create_order(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 1}],
        )
        validate_success(
            api.discontinue_product(world["products"][0]["id"], ADMIN), 200,
        )
        err = api.submit_order(order["id"], world["om_headers"])
        validate_error(err, ApiErrorId.ERR_PRODUCT_DISCONTINUED)
        assert get_order(order["id"])["fulfillment_status"] == "DRAFT"

    def test_planogram_ineligible_product_rejected(self, api):
        """PRD §3.3: "Slot products must exist — a dangling reference fails
        with `ERR_PRODUCT_NOT_FOUND` — and must be eligible for the location's
        `location_type`, else `ERR_PRODUCT_NOT_ELIGIBLE_FOR_LOCATION_TYPE`."

        Design: Corner/errors/planogram_ineligible_product_rejected
        """
        op = create_operator("Op Mix")
        route = create_route("R-MIX", ("MON",), 50, 0)
        product = create_product(
            sku="NRG-09", name="Energy drink case", category="BEVERAGE",
            eligible_location_types=["OFFICE", "GYM"], case_pack_qty=24,
            base_price_cents=1800, cost_cents=1080, shelf_life_days=270,
        )
        loc = create_location(op["id"], route["id"], "L-School", "SCHOOL")
        err = api.create_planogram(
            {
                "location_id": loc["id"],
                "name": "PG-School",
                "slots": [{"slot_code": "A1", "product_id": product["id"],
                           "par_level_units": 24, "vend_price_cents": 250}],
            },
            make_operator_manager_headers(op["id"]),
        )
        validate_error(err, ApiErrorId.ERR_PRODUCT_NOT_ELIGIBLE_FOR_LOCATION_TYPE)
