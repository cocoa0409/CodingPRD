"""Delivery routes: assignment OCC, supersede, lock/dispatch gates, freight."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_box_line,
    assign_order_to_route,
    create_assembly_line,
    create_dealer,
    create_draft_order,
    create_finish,
    create_modification_payload,
    create_route,
    create_submitted_box_order,
    get_success_data,
    make_dealer_headers,
    qc_release_batch,
    setup_door_order_in_production,
    setup_door_order_ready_to_ship,
    setup_shortage_hold_environment,
    slot_and_complete_box_line,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["plant_admin_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
SHIPPING = TEST_USERS["shipping_coordinator_headers"]


def _route_by_id(api, route_id):
    rows, _meta = validate_paginated(api.list_delivery_routes(SHIPPING))
    matches = [r for r in rows if r["id"] == route_id]
    assert matches, f"route {route_id} must be listed"
    return matches[0]


class TestRouteStateGates:
    def test_lock_empty_route_rejected(self, api):
        """PRD §3.9: "Locking a route commits its manifest: the route must be
        `PLANNED` (`ERR_ROUTE_NOT_PLANNED`), at least one order must be assigned
        (`ERR_ROUTE_EMPTY`, HTTP 409), and no assigned order may be `ON_HOLD`
        (`ERR_ORDER_ON_HOLD`, HTTP 409)."

        Design: Corner/state_machines/lock_empty_route_rejected
        """
        route = create_route(route_code="RT-E", route_date="2026-05-06", capacity_cu_ft=100.0)
        resp = api.lock_route(route["id"], SHIPPING)
        validate_error(resp, ApiErrorId.ERR_ROUTE_EMPTY)
        assert _route_by_id(api, route["id"])["status"] == "PLANNED"

    def test_dispatch_planned_route_rejected(self, api):
        """PRD §3.9: "A locked route waits only on readiness: dispatch requires the
        route in `LOCKED` (`ERR_ROUTE_NOT_LOCKED`, HTTP 409) and every assigned
        order in `READY_TO_SHIP` (`ERR_ORDERS_NOT_READY_TO_SHIP`, HTTP 409)."

        Design: Corner/state_machines/dispatch_planned_route_rejected
        """
        route = create_route(route_code="RT-P", route_date="2026-05-06", capacity_cu_ft=100.0)
        resp = api.dispatch_route(route["id"], SHIPPING)
        validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_LOCKED)

    def test_assign_to_locked_route_rejected(self, api):
        """PRD §3.9: "The route must be `PLANNED` (`ERR_ROUTE_NOT_PLANNED`, HTTP
        409), and the order must be in `SUBMITTED`, `IN_PRODUCTION`, or
        `READY_TO_SHIP` — assigning an order in any other state is rejected with
        `ERR_ORDER_NOT_ROUTE_ASSIGNABLE` (HTTP 409)."

        Design: Corner/state_machines/assign_to_locked_route_rejected
        """
        env1 = create_submitted_box_order(price_level="L1", qty=10, unit_price=200000)
        env2 = create_submitted_box_order(price_level="L1", qty=10, unit_price=200000)
        route = create_route(route_code="RT-L", route_date="2026-05-06", capacity_cu_ft=500.0)
        assign_order_to_route(route, env1["order"])
        get_success_data(api.lock_route(route["id"], SHIPPING))
        fresh = get_success_data(api.get_order(env2["order"]["id"], SHIPPING))
        resp = api.assign_order_to_route(
            route["id"],
            {"order_id": env2["order"]["id"], "expected_order_version": fresh["version"]},
            SHIPPING,
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_PLANNED)

    def test_draft_order_not_route_assignable(self, api):
        """PRD §3.9: "The route must be `PLANNED` (`ERR_ROUTE_NOT_PLANNED`, HTTP
        409), and the order must be in `SUBMITTED`, `IN_PRODUCTION`, or
        `READY_TO_SHIP` — assigning an order in any other state is rejected with
        `ERR_ORDER_NOT_ROUTE_ASSIGNABLE` (HTTP 409)."

        Design: Corner/validations/draft_order_not_route_assignable
        """
        dealer = create_dealer(price_level="L1")
        finish = create_finish(upcharge_pct=0.0)
        order = create_draft_order(dealer)
        add_box_line(order, finish, qty=1)
        route = create_route(route_code="RT-D", route_date="2026-05-06", capacity_cu_ft=100.0)
        fresh = get_success_data(api.get_order(order["id"], SHIPPING))
        resp = api.assign_order_to_route(
            route["id"],
            {"order_id": order["id"], "expected_order_version": fresh["version"]},
            SHIPPING,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_ROUTE_ASSIGNABLE)

    def test_lock_route_with_held_order_rejected(self, api):
        """PRD §3.9: "Locking a route commits its manifest: the route must be
        `PLANNED` (`ERR_ROUTE_NOT_PLANNED`), at least one order must be assigned
        (`ERR_ROUTE_EMPTY`, HTTP 409), and no assigned order may be `ON_HOLD`
        (`ERR_ORDER_ON_HOLD`, HTTP 409)."
        PRD §2.9: "While `hold_status` is `ON_HOLD`, both auto-transitions are
        gated: the order does not advance regardless of how complete its lines
        are, and the order also blocks route locking."

        Design: Corner/validations/lock_route_with_held_order_rejected
        """
        env = setup_shortage_hold_environment(on_hand_qty=0, line_qty=1, line_width=15, line_height=30)
        order = get_success_data(api.get_order(env["order"]["id"], SHIPPING))
        assert order["hold_status"] == "ON_HOLD", "setup must leave the order ON_HOLD"
        route = create_route(route_code="RT-H", route_date="2026-05-06", capacity_cu_ft=100.0)
        get_success_data(
            api.assign_order_to_route(
                route["id"],
                {"order_id": order["id"], "expected_order_version": order["version"]},
                SHIPPING,
            )
        )
        resp = api.lock_route(route["id"], SHIPPING)
        validate_error(resp, ApiErrorId.ERR_ORDER_ON_HOLD)
        assert _route_by_id(api, route["id"])["status"] == "PLANNED"


class TestRouteCapacity:
    def test_route_cube_exceeded_on_assign(self, api):
        """PRD §3.9: "Capacity is a fiscal-grade ceiling: the route's
        `reserved_cu_ft` plus the order's `cube_ft` must not exceed
        `capacity_cu_ft`, else `ERR_ROUTE_CUBE_EXCEEDED` (HTTP 402)."

        Design: Corner/validations/route_cube_exceeded_on_assign
        """
        env = create_submitted_box_order(price_level="L1", qty=10, unit_price=200000)
        # cube = 24 x 30 x 12 x 10 / 1728 = 50.0 ft3; route capacity is 40.0.
        route = create_route(route_code="RT-S", route_date="2026-05-06", capacity_cu_ft=40.0)
        fresh = get_success_data(api.get_order(env["order"]["id"], SHIPPING))
        resp = api.assign_order_to_route(
            route["id"],
            {"order_id": env["order"]["id"], "expected_order_version": fresh["version"]},
            SHIPPING,
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_CUBE_EXCEEDED)
        route_after = _route_by_id(api, route["id"])
        assert route_after["reserved_cu_ft"] == pytest.approx(0.0)
        order_after = get_success_data(api.get_order(env["order"]["id"], SHIPPING))
        assert order_after["delivery_route_id"] is None


class TestOptimisticConcurrency:
    def test_occ_stale_order_version_rejected(self, api):
        """PRD §2.8: "If the order's current `version` has advanced beyond that
        observed value — for example because the order was legitimately re-homed
        to a different route under the supersede rule, or because a submit or
        cancellation cascade bumped the version — the assignment is rejected with
        `ERR_STALE_ORDER_VERSION` (HTTP 412)."
        PRD §3.9: "The order's `version` increments on every assignment."

        Design: Corner/cross_cutting_layers/occ_stale_order_version_rejected
        """
        env = create_submitted_box_order(price_level="L1", qty=1, unit_price=50000)
        r1 = create_route(route_code="RT-1", route_date="2026-05-06", capacity_cu_ft=100.0)
        r2 = create_route(route_code="RT-2", route_date="2026-05-06", capacity_cu_ft=100.0)
        observed = get_success_data(api.get_order(env["order"]["id"], SHIPPING))
        # First assign succeeds and bumps the order version.
        assign_order_to_route(r1, observed)
        # The second assign carries the previously observed (now stale) version.
        resp = api.assign_order_to_route(
            r2["id"],
            {"order_id": env["order"]["id"], "expected_order_version": observed["version"]},
            SHIPPING,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION)
        r1_after = _route_by_id(api, r1["id"])
        r2_after = _route_by_id(api, r2["id"])
        assert r1_after["reserved_cu_ft"] == pytest.approx(5.0), "order must remain on R1"
        assert r2_after["reserved_cu_ft"] == pytest.approx(0.0)


class TestSupersedeConservation:
    def _order_and_two_routes(self, api):
        env = create_submitted_box_order(price_level="L1", qty=10, unit_price=200000)
        r1 = create_route(route_code="RT-X", route_date="2026-05-06", capacity_cu_ft=100.0)
        r2 = create_route(route_code="RT-Y", route_date="2026-05-06", capacity_cu_ft=100.0)
        return env, r1, r2

    def test_supersede_moves_cube_between_routes(self, api):
        """PRD §3.9: "Assignment supersedes: the order's `delivery_route_id` is set
        to the new route, and if the order had sat on a prior route, that route's
        `reserved_cu_ft` and `assigned_order_count` are decremented accordingly —
        so a second sequential assignment carrying a current version legitimately
        succeeds. The receiving route's `reserved_cu_ft` increases by the order's
        `cube_ft`, its `assigned_order_count` increases by one, and the order's
        `route_stop_seq` is assigned as a 1-based sequence in the order that
        assignment calls are accepted, earliest accepted assignment first."

        Design: Difficulty/compensating_invariant/route_cube_conserved_under_reassignment
        """
        env, r1, r2 = self._order_and_two_routes(api)
        first = assign_order_to_route(r1, env["order"])
        assert first["route"]["reserved_cu_ft"] == pytest.approx(50.0)
        second = assign_order_to_route(r2, first["order"])
        assert second["route"]["reserved_cu_ft"] == pytest.approx(50.0)
        assert second["route"]["assigned_order_count"] == 1
        assert second["order"]["delivery_route_id"] == r2["id"]
        r1_after = _route_by_id(api, r1["id"])
        assert r1_after["reserved_cu_ft"] == pytest.approx(0.0), (
            "the prior route's reservation must be compensated exactly"
        )
        assert r1_after["assigned_order_count"] == 0

    def test_total_reserved_cube_is_conserved(self, api):
        """PRD §3.9: "Assignment supersedes: the order's `delivery_route_id` is set
        to the new route, and if the order had sat on a prior route, that route's
        `reserved_cu_ft` and `assigned_order_count` are decremented accordingly —
        so a second sequential assignment carrying a current version legitimately
        succeeds."
        PRD §3.2: "the order's `cube_ft` is the sum of those per-line cubes, again
        rounded half up to two decimal places."

        Design: Difficulty/compensating_invariant/route_cube_conserved_under_reassignment
        """
        env, r1, r2 = self._order_and_two_routes(api)
        order_cube = get_success_data(api.get_order(env["order"]["id"], SHIPPING))["cube_ft"]
        assert order_cube == pytest.approx(50.0)
        assign_order_to_route(r1, env["order"])
        r1_mid = _route_by_id(api, r1["id"])
        r2_mid = _route_by_id(api, r2["id"])
        assert r1_mid["reserved_cu_ft"] + r2_mid["reserved_cu_ft"] == pytest.approx(50.0)
        assign_order_to_route(r2, get_success_data(api.get_order(env["order"]["id"], SHIPPING)))
        r1_end = _route_by_id(api, r1["id"])
        r2_end = _route_by_id(api, r2["id"])
        total = r1_end["reserved_cu_ft"] + r2_end["reserved_cu_ft"]
        assert total == pytest.approx(50.0), (
            "reserved cube across all routes must equal the order's cube at every step"
        )


class TestRouteStopSequence:
    def test_route_stop_sequence_follows_accepted_assign_order(self, api):
        """PRD §3.9: "The receiving route's `reserved_cu_ft` increases by the
        order's `cube_ft`, its `assigned_order_count` increases by one, and the
        order's `route_stop_seq` is assigned as a 1-based sequence in the order
        that assignment calls are accepted, earliest accepted assignment first."

        Design: Corner/endpoints/route_stop_sequence_follows_accepted_assign_order
        """
        env1 = create_submitted_box_order(price_level="L1", qty=1, unit_price=50000)
        env2 = create_submitted_box_order(price_level="L1", qty=1, unit_price=50000)
        route = create_route(route_code="RT-S", route_date="2026-05-06", capacity_cu_ft=100.0)
        # The second-created order is assigned first.
        assign_order_to_route(route, env2["order"])
        assign_order_to_route(route, env1["order"])
        o2 = validate_success(api.get_order(env2["order"]["id"], SHIPPING))
        o1 = validate_success(api.get_order(env1["order"]["id"], SHIPPING))
        assert o2["route_stop_seq"] == 1, "earliest accepted assignment takes stop 1"
        assert o1["route_stop_seq"] == 2


class TestDispatchGating:
    def _locked_route_with_unreleased_batch_order(self, api):
        env = setup_door_order_in_production(price_level="L4", qty=4, unit_price=30000, upcharge_pct=0.10)
        route = create_route(route_code="RT-D", route_date="2026-05-04", capacity_cu_ft=100.0)
        assign_order_to_route(route, env["order"])
        get_success_data(api.lock_route(route["id"], SHIPPING))
        return env, route

    def test_dispatch_blocked_while_order_not_ready(self, api):
        """PRD §3.9: "A locked route waits only on readiness: dispatch requires the
        route in `LOCKED` (`ERR_ROUTE_NOT_LOCKED`, HTTP 409) and every assigned
        order in `READY_TO_SHIP` (`ERR_ORDERS_NOT_READY_TO_SHIP`, HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/dispatch_gated_by_order_readiness_state
        """
        env, route = self._locked_route_with_unreleased_batch_order(api)
        order = get_success_data(api.get_order(env["order"]["id"], SHIPPING))
        assert order["status"] == "IN_PRODUCTION", "batch not yet QC-released"
        resp = api.dispatch_route(route["id"], SHIPPING)
        validate_error(resp, ApiErrorId.ERR_ORDERS_NOT_READY_TO_SHIP)
        assert _route_by_id(api, route["id"])["status"] == "LOCKED"

    def test_dispatch_succeeds_after_batch_release(self, api):
        """PRD §3.7: "From `IN_PRODUCTION`, an order auto-advances to
        `READY_TO_SHIP` when its `hold_status` is `NONE` and every line is
        `COMPLETED` — door lines complete when their batch QC-releases, box lines
        when their last sub-lot completes — and this evaluation runs after each
        batch QC release, sub-lot completion, and hold release."
        PRD §3.9: "As dispatch executes, every assigned order moves
        `READY_TO_SHIP` → `SHIPPED`, each of its lines moves `COMPLETED` →
        `SHIPPED` with its final net computed, `shipped_at` is stamped from the
        logical clock, and each order's `version` increments."

        Design: Difficulty/cross_entity_state_dependency/dispatch_gated_by_order_readiness_state
        """
        env, route = self._locked_route_with_unreleased_batch_order(api)
        first = api.dispatch_route(route["id"], SHIPPING)
        validate_error(first, ApiErrorId.ERR_ORDERS_NOT_READY_TO_SHIP)
        # The batch QC pass cascades the order to READY_TO_SHIP.
        qc_release_batch(env["batch"], measured_delta_e=1.0)
        order = get_success_data(api.get_order(env["order"]["id"], SHIPPING))
        assert order["status"] == "READY_TO_SHIP"
        dispatched = validate_success(api.dispatch_route(route["id"], SHIPPING))
        assert dispatched["status"] == "DISPATCHED"
        shipped = get_success_data(api.get_order(env["order"]["id"], SHIPPING))
        assert shipped["status"] == "SHIPPED"


class TestFreightConsolidation:
    def _three_ready_orders_on_one_route(self, api):
        dealer = create_dealer(price_level="L1")
        finish = create_finish(upcharge_pct=0.0)
        assembly_line = create_assembly_line(
            line_code="AL-C", capacity_minutes_per_day=2000,
            standard_minutes_per_box=30, setup_minutes_per_sub_lot=20,
        )
        route = create_route(route_code="RT-3", route_date="2026-05-05", capacity_cu_ft=1000.0)
        orders = []
        for start in (60, 380, 700):
            order = create_draft_order(dealer)
            line = add_box_line(order, finish, qty=10, unit_price=200000)
            get_success_data(api.submit_order(order["id"], make_dealer_headers(dealer["id"])))
            slot_and_complete_box_line(line, assembly_line=assembly_line, start_minute=start)
            ready = get_success_data(api.get_order(order["id"], ADMIN))
            assert ready["status"] == "READY_TO_SHIP"
            assign_order_to_route(route, ready)
            orders.append(ready)
        get_success_data(api.lock_route(route["id"], SHIPPING))
        return route, orders

    def test_dispatch_tier_read_from_count_at_dispatch_for_all_orders(self, api):
        """PRD §3.9: "then the consolidation tier read from the route's
        `assigned_order_count` at the dispatch instant — a count that includes the
        order being priced and is identical for every order on the route —
        granting fifteen percent off when at least five orders ride the route, ten
        percent off when at least three but fewer than five do, and no
        consolidation below three; then `freight_cents` as the base freight
        reduced by the consolidation percentage, rounded half up."

        Design: Difficulty/combinatorial_formula/freight_consolidation_pinned_evaluation_order
        """
        route, orders = self._three_ready_orders_on_one_route(api)
        validate_success(api.dispatch_route(route["id"], SHIPPING))
        # base freight max(8,500, round(50.0 x 450)) = 22,500; count 3 -> 10%:
        # round(22,500 x 0.90) = 20,250 for every order, regardless of the count
        # at each order's own assign instant.
        for order in orders:
            shipped = get_success_data(api.get_order(order["id"], SHIPPING))
            assert shipped["freight_cents"] == 20250, (
                f"order {order['id']} freight must use count-at-dispatch (3), got "
                f"{shipped['freight_cents']}"
            )

    def test_grand_total_combines_final_merchandise_and_consolidated_freight(self, api):
        """PRD §3.9: "The order's `grand_total_cents` is `final_merchandise_cents`
        minus `final_discount_cents` plus `freight_cents`, frozen at dispatch."
        PRD §3.9: "First the order's cube; then the base freight, which is the
        greater of an 8,500-cent flat minimum and the order's `cube_ft` multiplied
        by 450 cents per cubic foot, rounded half up to whole cents"

        Design: Difficulty/combinatorial_formula/freight_consolidation_pinned_evaluation_order
        """
        route, orders = self._three_ready_orders_on_one_route(api)
        validate_success(api.dispatch_route(route["id"], SHIPPING))
        shipped = get_success_data(api.get_order(orders[0]["id"], SHIPPING))
        # L1: final merchandise round(2,000,000 x 0.60) = 1,200,000; no tier.
        assert shipped["final_merchandise_cents"] == 1200000
        assert shipped["final_discount_cents"] == 0
        assert shipped["grand_total_cents"] == 1220250, (
            "1,200,000 - 0 + 20,250"
        )


class TestFinalPricingVariant:
    def _shipped_box_order_with_approved_mod(self, api):
        dealer = create_dealer(price_level="L2")
        finish = create_finish(upcharge_pct=0.10, finish_code="FS-SAT-10",
                               color_name="Oak Satin", sheen="SATIN")
        order = create_draft_order(dealer)
        line = add_box_line(order, finish, qty=10, unit_price=200000)
        mod = get_success_data(
            api.create_modification(
                line["id"],
                create_modification_payload(mod_code="INCREASED_DEPTH", new_dimension_in=20),
                make_dealer_headers(dealer["id"]),
            )
        )
        get_success_data(api.review_modification(mod["id"], {"decision": "APPROVE", "note": "ok"}, ENGINEER))
        submitted = get_success_data(api.submit_order(order["id"], make_dealer_headers(dealer["id"])))
        assembly_line = create_assembly_line(
            line_code="AL-1", capacity_minutes_per_day=480,
            standard_minutes_per_box=30, setup_minutes_per_sub_lot=20,
        )
        slot_and_complete_box_line(line, assembly_line=assembly_line, start_minute=60)
        route = create_route(route_code="RT-1", route_date="2026-05-04", capacity_cu_ft=500.0)
        assign_order_to_route(route, submitted)
        get_success_data(api.lock_route(route["id"], SHIPPING))
        return {"dealer": dealer, "order": submitted, "line": line, "route": route}

    def test_provisional_and_final_variants_diverge_on_same_lines(self, api):
        """PRD §3.2: "The provisional pricing variant discounts everything."
        PRD §3.9: "Alongside freight, the final pricing variant settles the
        merchandise: each line's `final_net_cents` is the `line_list_cents`
        multiplied by the snapshotted dealer multiplier and rounded half up, plus
        the `finish_upcharge_cents` and `mod_surcharge_cents` charged at full
        value — surcharges and upcharges are not discountable at settlement,
        unlike at submission, so for identical line data the final net exceeds the
        provisional net whenever upcharges plus surcharges are positive and the
        multiplier is below one."

        Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_final_variant
        """
        env = self._shipped_box_order_with_approved_mod(api)
        validate_success(api.dispatch_route(env["route"]["id"], SHIPPING))
        order = get_success_data(api.get_order(env["order"]["id"], SHIPPING))
        # provisional: round((2,000,000 + 200,000 + 304,000) x 0.65) = 1,627,600.
        assert order["provisional_merchandise_cents"] == 1627600
        assert order["provisional_total_cents"] == 1627600, "below the 5,000,000 tier"
        # final: round(2,000,000 x 0.65) + 200,000 + 304,000 = 1,804,000.
        assert order["final_merchandise_cents"] == 1804000
        assert order["final_merchandise_cents"] != order["provisional_merchandise_cents"], (
            "the settlement variant must charge upcharge and surcharges at full value"
        )

    def test_dispatch_freezes_freight_grand_total_and_ships(self, api):
        """PRD §3.9: "First the order's cube; then the base freight, which is the
        greater of an 8,500-cent flat minimum and the order's `cube_ft` multiplied
        by 450 cents per cubic foot, rounded half up to whole cents"
        PRD §3.9: "The order's `grand_total_cents` is `final_merchandise_cents`
        minus `final_discount_cents` plus `freight_cents`, frozen at dispatch."
        PRD §3.9: "As dispatch executes, every assigned order moves
        `READY_TO_SHIP` → `SHIPPED`, each of its lines moves `COMPLETED` →
        `SHIPPED` with its final net computed, `shipped_at` is stamped from the
        logical clock, and each order's `version` increments."

        Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_final_variant
        """
        env = self._shipped_box_order_with_approved_mod(api)
        validate_success(api.dispatch_route(env["route"]["id"], SHIPPING))
        order = get_success_data(api.get_order(env["order"]["id"], SHIPPING))
        # cube 50.0 -> base max(8,500, 22,500) = 22,500; single-order route -> 0%.
        assert order["freight_cents"] == 22500
        assert order["grand_total_cents"] == 1826500, "1,804,000 - 0 + 22,500"
        assert order["status"] == "SHIPPED"
        line = get_success_data(api.get_order_line(env["line"]["id"], SHIPPING))
        assert line["status"] == "SHIPPED"
        assert line["final_net_cents"] == 1804000


class TestFreightFlatMinimum:
    def test_freight_flat_minimum_binds_for_small_cube(self, api):
        """PRD §3.9: "First the order's cube; then the base freight, which is the
        greater of an 8,500-cent flat minimum and the order's `cube_ft` multiplied
        by 450 cents per cubic foot, rounded half up to whole cents"

        Design: Corner/calculations/freight_flat_minimum_binds_for_small_cube
        """
        env = setup_door_order_ready_to_ship(price_level="L4", qty=1, unit_price=30000, upcharge_pct=0.10)
        route = create_route(route_code="RT-F", route_date="2026-05-04", capacity_cu_ft=100.0)
        assign_order_to_route(route, env["order"])
        get_success_data(api.lock_route(route["id"], SHIPPING))
        validate_success(api.dispatch_route(route["id"], SHIPPING))
        order = get_success_data(api.get_order(env["order"]["id"], SHIPPING))
        # cube = 15 x 30 x 1 x 1 / 1728 = 0.26 ft3; cube-rate freight round(0.26 x
        # 450) = 117 < 8,500 flat minimum.
        assert order["cube_ft"] == pytest.approx(0.26)
        assert order["freight_cents"] == 8500, "the 8,500-cent flat minimum must bind"
