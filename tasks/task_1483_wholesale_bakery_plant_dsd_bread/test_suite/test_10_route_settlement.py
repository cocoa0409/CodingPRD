"""Route settlement: shrink accounting, driver liability accrual, capacity
boundary, and validation priority (PRD §3.6, §3.7, §2.9)."""
from test_helpers import (
    TEST_USERS,
    create_batch,
    create_line,
    create_order,
    create_plan,
    create_plant,
    create_product,
    create_route,
    create_stop,
    create_store,
    create_driver,
    confirm_order,
    lock_order,
    lock_plan,
    make_driver_headers,
    release_plan,
    set_clock,
    setup_delivered_stop_scenario,
    setup_dispatched_route_scenario,
    setup_released_batch_scenario,
    validate_error,
    validate_success,
    walk_batch_to_released,
)


class TestRouteSettleShrinkLiability:
    def test_route_settle_shrink_liability_literal(self, api):
        """PRD §3.7: "Shrink is then `shrink_units` equals `loaded_units` minus
        the delivered total." And: "Driver liability engages only when the
        ratio exceeds the 2% tolerance: liability units are then
        `shrink_units` minus the tolerated allowance of `loaded_units`
        multiplied by 0.02 and rounded up to a whole unit, floored at zero."
        And: "The route's `shrink_liability_cents` is the liability units
        multiplied by a penalty of 150 cents per unit, and settlement adds
        that amount onto the driver's cumulative `shrink_liability_cents`."

        Design: Corner/calculations/route_settle_shrink_liability_literal
        """
        plant = create_plant(name="Plant P")
        product_a = create_product(plant["id"])
        store1 = create_store(plant["id"], name="S1", shelf_capacity_units=500)
        store2 = create_store(plant["id"], name="S2", shelf_capacity_units=100)
        driver = create_driver(plant["id"])
        line = create_line(plant["id"])

        set_clock("2026-08-06T00:00:00Z")
        o1 = create_order(store1["id"], product_a["id"], qty=100)
        confirm_order(o1["id"]); lock_order(o1["id"])
        o2 = create_order(store2["id"], product_a["id"], qty=100)
        confirm_order(o2["id"]); lock_order(o2["id"])

        plan = create_plan(plant["id"], expected_plant_version=plant["version"])
        locked_plan = lock_plan(plan["id"])
        batch = create_batch(
            plan["id"], line["id"], product_a["id"],
            plan_version=locked_plan["version"], qty_units=200,
        )
        release_plan(plan["id"])
        set_clock("2026-08-09T07:50:00Z")
        batch = walk_batch_to_released(batch["id"], operator_id="op-1", qa_id="qa-1")

        route = create_route(plant["id"], driver["id"], truck_capacity_units=250)
        sp1 = create_stop(route["id"], o1["id"], 100, [batch["id"]])
        sp2 = create_stop(route["id"], o2["id"], 100, [batch["id"]])

        hdrs = make_driver_headers(driver["id"])
        validate_success(api.start_loading(route["id"], hdrs))
        validate_success(api.dispatch_route(route["id"], hdrs))
        set_clock("2026-08-10T09:00:00Z")
        # stop1 delivers fully (100); stop2 delivers 95 with shelf room for 20.
        validate_success(api.deliver_route_stop(
            sp1["id"], {"delivered_units": 100, "on_shelf_units_observed": 0}, hdrs
        ))
        sp2_after = validate_success(api.deliver_route_stop(
            sp2["id"], {"delivered_units": 95, "on_shelf_units_observed": 80}, hdrs
        ))
        # min(95, max(0, 100-80)) = 20 stocked; 75 refused.
        assert sp2_after["stocked_units"] == 20
        assert sp2_after["refused_units"] == 75

        validate_success(api.complete_route(route["id"], hdrs))
        settled = validate_success(
            api.settle_route(route["id"], {}, TEST_USERS["planner_headers"])
        )
        # loaded 200 - delivered (100+95) = shrink 5. ratio 5/200 = 2.5% > 2%.
        # liability_units = 5 - ceil(200*0.02) = 5-4 = 1; cents = 1*150 = 150.
        assert settled["status"] == "SETTLED"
        assert settled["shrink_units"] == 5, (
            f"shrink must be 200-195=5, got {settled['shrink_units']}"
        )
        assert settled["shrink_liability_cents"] == 150, (
            f"liability must be (5-4)*150=150, got {settled['shrink_liability_cents']}"
        )

        driver_after = validate_success(
            api.get_driver(driver["id"], TEST_USERS["planner_headers"])
        )
        assert driver_after["shrink_liability_cents"] == 150, (
            f"driver liability must accrue 150, got {driver_after['shrink_liability_cents']}"
        )


class TestRouteCapacityExactBoundary:
    def test_route_capacity_exact_boundary(self, api):
        """PRD §3.6: "Dispatching moves `LOADING` to `DISPATCHED` and enforces
        the truck: `loaded_units` must not exceed `truck_capacity_units`,
        else `ERR_ROUTE_CAPACITY_EXCEEDED`."

        Design: Corner/errors/route_capacity_exact_boundary
        """
        plant = create_plant(name="Plant P Cap")
        product_a = create_product(plant["id"])
        store1 = create_store(plant["id"], name="S1", shelf_capacity_units=500)
        store2 = create_store(plant["id"], name="S2", shelf_capacity_units=500)
        driver = create_driver(plant["id"])
        line = create_line(plant["id"])

        set_clock("2026-08-06T00:00:00Z")
        o1 = create_order(store1["id"], product_a["id"], qty=101)
        confirm_order(o1["id"]); lock_order(o1["id"])
        o2 = create_order(store2["id"], product_a["id"], qty=100)
        confirm_order(o2["id"]); lock_order(o2["id"])

        plan = create_plan(plant["id"], expected_plant_version=plant["version"])
        locked_plan = lock_plan(plan["id"])
        batch = create_batch(
            plan["id"], line["id"], product_a["id"],
            plan_version=locked_plan["version"], qty_units=201,
        )
        release_plan(plan["id"])
        set_clock("2026-08-09T07:50:00Z")
        batch = walk_batch_to_released(batch["id"], operator_id="op-1", qa_id="qa-1")

        # Route 1 loaded 101 over capacity 100 — over by one.
        r1 = create_route(plant["id"], driver["id"], truck_capacity_units=100)
        create_stop(r1["id"], o1["id"], 101, [batch["id"]])
        hdrs = make_driver_headers(driver["id"])
        validate_success(api.start_loading(r1["id"], hdrs))

        # Route 2 loaded exactly 100 on capacity 100 — boundary inclusive.
        # Window starts 30 minutes after route 1's window ends (12:00), so the
        # rest-buffer rule of §3.6 does not reject it.
        r2 = create_route(
            plant["id"], driver["id"],
            window_start_at="2026-08-10T12:30:00Z",
            window_end_at="2026-08-10T14:00:00Z",
            truck_capacity_units=100,
        )
        create_stop(r2["id"], o2["id"], 100, [batch["id"]])
        validate_success(api.start_loading(r2["id"], hdrs))

        resp1 = api.dispatch_route(r1["id"], hdrs)
        validate_error(resp1, "ERR_ROUTE_CAPACITY_EXCEEDED", expected_status=409)

        dispatched2 = validate_success(api.dispatch_route(r2["id"], hdrs))
        assert dispatched2["status"] == "DISPATCHED", (
            f"loaded == capacity must dispatch (<= semantics), got {dispatched2['status']}"
        )


class TestSettleStateViolationBeatsShrinkFiscal:
    def test_settle_from_dispatched_state_violation(self, api):
        """PRD §3.7: "Settlement closes the financial loop on a `COMPLETED`
        route and is a `Planner` action." PRD §2.9 step 6: "State
        preconditions — the target resource is in a valid from-state for
        the requested transition, including: the plan is released before a
        batch may start mixing, the pickup stop is delivered before a stale
        return enters the credit chain, and batches are released before
        delivery; failure yields `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/settle_state_violation_beats_shrink_fiscal
        """
        ctx = setup_dispatched_route_scenario(
            plant_name="Plant Lambda", order_qty=100
        )
        route = ctx["route"]

        # The route is DISPATCHED with zero delivered so far — settle would
        # also violate the shrink hard limit (100% shrink), but the state
        # check (priority 6) fires before the fiscal check (priority 10).
        resp = api.settle_route(route["id"], {}, TEST_USERS["planner_headers"])
        validate_error(resp, "ERR_INVALID_STATE", expected_status=409)

    def test_settle_state_violation_leaves_route_unchanged(self, api):
        """PRD §2.6: "Resources in a terminal state are locked down: any
        action that names a terminal resource as its target is rejected with
        `ERR_INVALID_STATE` (HTTP 409) rather than partially applied." (The
        same no-partial-application rule covers a rejected transition from a
        non-terminal state.)

        Design: Difficulty/priority_pair_validation_conflict/settle_state_violation_beats_shrink_fiscal
        """
        ctx = setup_dispatched_route_scenario(
            plant_name="Plant Lambda 2", order_qty=100
        )
        route = ctx["route"]

        resp = api.settle_route(route["id"], {}, TEST_USERS["planner_headers"])
        validate_error(resp, "ERR_INVALID_STATE", expected_status=409)

        route_after = validate_success(
            api.get_route(route["id"], TEST_USERS["planner_headers"])
        )
        assert route_after["status"] == "DISPATCHED", (
            f"rejected settle must leave route DISPATCHED, got {route_after['status']}"
        )


class TestShrinkHardLimitOverride:
    def test_shrink_hard_limit_blocks_settle_without_override(self, api):
        """PRD §3.7: "If the ratio exceeds 0.10 the settle is rejected with
        `ERR_SHRINK_LIMIT_EXCEEDED` — unless the planner deliberately passes
        `override_shrink_limit` set to true." And: "liability units are then
        `shrink_units` minus the tolerated allowance of `loaded_units`
        multiplied by 0.02 and rounded up to a whole unit, floored at zero."

        Design: Corner/errors/shrink_hard_limit_blocks_settle_without_override
        """
        # Shelf 500 so the full 80 delivered units fit (refused 0).
        ctx = setup_delivered_stop_scenario(
            plant_name="Plant P Override",
            order_qty=100,
            delivered_units=80,
            store_overrides={"shelf_capacity_units": 500},
        )
        route = ctx["route"]
        driver = ctx["driver"]
        hdrs = make_driver_headers(driver["id"])
        validate_success(api.complete_route(route["id"], hdrs))

        # shrink = 100-80 = 20; 20/100 = 20% > 10% hard limit.
        resp = api.settle_route(route["id"], {}, TEST_USERS["planner_headers"])
        validate_error(resp, "ERR_SHRINK_LIMIT_EXCEEDED", expected_status=409)

        # With the explicit override the settle goes through and posts
        # liability: (20 - ceil(100*0.02)) * 150 = 18 * 150 = 2700.
        settled = validate_success(
            api.settle_route(
                route["id"], {"override_shrink_limit": True}, TEST_USERS["planner_headers"]
            )
        )
        assert settled["status"] == "SETTLED"
        assert settled["shrink_liability_cents"] == 2700, (
            f"liability must be 18*150=2700, got {settled['shrink_liability_cents']}"
        )
