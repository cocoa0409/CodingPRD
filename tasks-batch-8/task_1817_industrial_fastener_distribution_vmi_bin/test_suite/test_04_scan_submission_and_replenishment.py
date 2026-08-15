"""Scan submission: parent-state gating, reorder-point boundary, count bounds,
idempotent re-trigger rejection, posture auto-transitions, derived-field
reconciliation through the delivery chain, and FK reverse reachability."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_route_stop,
    create_route,
    create_stop,
    get_success_data,
    is_valid_uuid,
    setup_confirmed_order,
    setup_draft_order,
    setup_site_part_agreement,
    setup_started_route_with_stop,
    start_route,
    submit_stop,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
DRIVER = TEST_USERS["driver_headers"]
OPERATOR = TEST_USERS["operator_headers"]


class TestSubmitRouteStateGate:
    def test_submit_requires_route_in_progress(self, api):
        """PRD §3.3: "Submission requires the route to be `IN_PROGRESS` and the
        agreement to be in `ACTIVE` or `AT_CAPACITY`; a `RETIRED` site or
        agreement surfaces `ERR_AGREEMENT_OR_SITE_RETIRED`."
        PRD §2.8: "transition legality — the target resource must be in a state
        from which the requested transition exists, surfacing
        `ERR_INVALID_STATE`".

        Design: Difficulty/cross_entity_state_dependency/stop_submit_requires_route_in_progress
        """
        ctx = setup_site_part_agreement(api, min_qty=10, max_qty=100)
        route = create_route(api, ctx["site"]["id"])
        stop = create_stop(api, route["id"], ctx["agreement"]["id"])
        resp = api.submit_route_stop(stop["id"], {"counted_qty": 5}, DRIVER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = get_success_data(api.get_route_stop(stop["id"], DRIVER))
        assert after["status"] == "PENDING", (
            "a stop on a SCHEDULED route cannot be submitted"
        )

    def test_submit_succeeds_once_route_started(self, api):
        """PRD §3.3: "Submission requires the route to be `IN_PROGRESS` and the
        agreement to be in `ACTIVE` or `AT_CAPACITY`; a `RETIRED` site or
        agreement surfaces `ERR_AGREEMENT_OR_SITE_RETIRED`."
        PRD §3.3: "When the count lands strictly below the agreement's
        `min_qty`, the system creates a replenishment order in `DRAFT` status
        for that agreement with `ordered_qty` equal to `max_qty` minus the
        counted quantity, priced immediately per §3.4, and records the new
        order's id in the stop's `generated_order_id`; when the count is at or
        above `min_qty`, no order is created and `generated_order_id` stays
        null."

        Design: Difficulty/cross_entity_state_dependency/stop_submit_requires_route_in_progress
        """
        ctx = setup_site_part_agreement(api, min_qty=10, max_qty=100)
        route = create_route(api, ctx["site"]["id"])
        stop = create_stop(api, route["id"], ctx["agreement"]["id"])
        start_route(api, route["id"])
        submitted = submit_stop(api, stop["id"], 5)
        assert submitted["status"] == "SUBMITTED"
        assert is_valid_uuid(submitted["generated_order_id"])
        order = get_success_data(
            api.get_replenishment_order(submitted["generated_order_id"], ADMIN))
        assert order["status"] == "DRAFT"
        assert order["ordered_qty"] == 95


class TestReorderPointBoundary:
    def test_scan_at_min_qty_generates_no_order(self, api):
        """PRD §3.3: "When the count lands strictly below the agreement's
        `min_qty`, the system creates a replenishment order in `DRAFT` status
        for that agreement with `ordered_qty` equal to `max_qty` minus the
        counted quantity, priced immediately per §3.4, and records the new
        order's id in the stop's `generated_order_id`; when the count is at or
        above `min_qty`, no order is created and `generated_order_id` stays
        null."

        Design: Difficulty/boundary_precision_check/scan_count_exactly_at_min_triggers_no_order
        """
        ctx = setup_site_part_agreement(api, min_qty=10, max_qty=100)
        rs = setup_started_route_with_stop(
            api, ctx["site"]["id"], ctx["agreement"]["id"])
        submitted = submit_stop(api, rs["stop"]["id"], 10)
        assert submitted["generated_order_id"] is None, (
            "a count exactly at the reorder point does not trigger"
        )
        agr = get_success_data(
            api.get_bin_agreement(ctx["agreement"]["id"], ADMIN))
        assert agr["on_hand_qty"] == 10
        assert agr["open_order_qty"] == 0

    def test_scan_one_below_min_qty_generates_fill_to_max_order(self, api):
        """PRD §3.3: "When the count lands strictly below the agreement's
        `min_qty`, the system creates a replenishment order in `DRAFT` status
        for that agreement with `ordered_qty` equal to `max_qty` minus the
        counted quantity, priced immediately per §3.4, and records the new
        order's id in the stop's `generated_order_id`; when the count is at or
        above `min_qty`, no order is created and `generated_order_id` stays
        null."

        Design: Difficulty/boundary_precision_check/scan_count_exactly_at_min_triggers_no_order
        """
        ctx = setup_site_part_agreement(api, min_qty=10, max_qty=100)
        rs = setup_started_route_with_stop(
            api, ctx["site"]["id"], ctx["agreement"]["id"])
        submitted = submit_stop(api, rs["stop"]["id"], 9)
        assert is_valid_uuid(submitted["generated_order_id"])
        order = get_success_data(
            api.get_replenishment_order(submitted["generated_order_id"], ADMIN))
        assert order["ordered_qty"] == 91, "fill-to-max: 100 - 9"
        assert order["status"] == "DRAFT"


class TestCountBoundsAndIdempotency:
    def test_counted_qty_above_max_rejected(self, api):
        """PRD §3.3: "Later, at the bin, the driver submits the physical count,
        transitioning the stop from `PENDING` to `SUBMITTED` with a
        `counted_qty` that must be zero or positive and no greater than the
        agreement's `max_qty` — a count above capacity is rejected with
        `ERR_QUANTITY_OUT_OF_BOUNDS`."

        Design: Corner/validations/counted_qty_above_max_rejected
        """
        ctx = setup_site_part_agreement(api, credit_limit_cents=100000,
                                        min_qty=10, max_qty=100)
        route = create_route(api, ctx["site"]["id"])
        start_route(api, route["id"])
        stop_over = create_stop(api, route["id"], ctx["agreement"]["id"])
        stop_eq = create_stop(api, route["id"], ctx["agreement"]["id"])

        resp = api.submit_route_stop(stop_over["id"], {"counted_qty": 101},
                                     DRIVER)
        validate_error(resp, ApiErrorId.ERR_QUANTITY_OUT_OF_BOUNDS, 422)

        accepted = submit_stop(api, stop_eq["id"], 100)
        assert accepted["status"] == "SUBMITTED"
        assert accepted["generated_order_id"] is None, (
            "a full bin (count == max >= min) generates no order"
        )
        agr = get_success_data(
            api.get_bin_agreement(ctx["agreement"]["id"], ADMIN))
        assert agr["on_hand_qty"] == 100

    def test_double_submit_rejected_no_duplicate_order(self, api):
        """PRD §3.7: "once any resource in this programme reaches a terminal
        state — `RETIRED`, `OBSOLETE`, `CLOSED`, `CANCELLED`, `DELIVERED`,
        `EXPIRED`, `COMPLETED`, or `SCRAPPED` — every further transition
        attempt against it is rejected with `ERR_INVALID_STATE`, including
        idempotent re-triggers of the transition that already fired."
        PRD §3.4: "Orders are listable with `bin_agreement_id`, `site_id`,
        `part_id`, and `status` filters."

        Design: Corner/state_machines/double_submit_stop_is_idempotency_rejection
        """
        ctx = setup_site_part_agreement(api, min_qty=10, max_qty=100)
        rs = setup_started_route_with_stop(
            api, ctx["site"]["id"], ctx["agreement"]["id"])
        first = submit_stop(api, rs["stop"]["id"], 5)
        assert first["generated_order_id"] is not None
        resp = api.submit_route_stop(rs["stop"]["id"], {"counted_qty": 5},
                                     DRIVER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        orders, meta = validate_paginated(
            api.list_replenishment_orders(
                ADMIN, params={"bin_agreement_id": ctx["agreement"]["id"]}))
        assert meta["total_count"] == 1, "no duplicate order may be created"

    def test_warehouse_operator_cannot_submit_route_stops(self, api):
        """PRD §2.1: "A request whose role is authenticated but not permitted
        on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403);
        the per-endpoint role assignments are listed in §4."
        PRD §4: POST /vmi/route-stops/{id}/submit — Authorized Role(s):
        RouteDriver.

        Design: Corner/roles/warehouse_operator_cannot_submit_route_stops
        """
        ctx = setup_site_part_agreement(api, credit_limit_cents=100000,
                                        min_qty=1, max_qty=10)
        rs = setup_started_route_with_stop(
            api, ctx["site"]["id"], ctx["agreement"]["id"])
        resp = api.submit_route_stop(rs["stop"]["id"], {"counted_qty": 5},
                                     OPERATOR)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        after = get_success_data(api.get_route_stop(rs["stop"]["id"], DRIVER))
        assert after["status"] == "PENDING"


class TestImmediateConsistencyAndPosture:
    def test_submit_response_immediately_reflects_cascade(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.3: "When the count lands strictly below the agreement's
        `min_qty`, the system creates a replenishment order in `DRAFT` status
        for that agreement with `ordered_qty` equal to `max_qty` minus the
        counted quantity, priced immediately per §3.4, and records the new
        order's id in the stop's `generated_order_id`; when the count is at or
        above `min_qty`, no order is created and `generated_order_id` stays
        null."

        Design: Corner/consistency_model/mutations_visible_immediately_in_same_response
        """
        ctx = setup_site_part_agreement(api, min_qty=10, max_qty=100)
        rs = setup_started_route_with_stop(
            api, ctx["site"]["id"], ctx["agreement"]["id"])
        resp = api.submit_route_stop(rs["stop"]["id"], {"counted_qty": 5},
                                     DRIVER)
        data = validate_success(resp, 200)
        assert data["status"] == "SUBMITTED", (
            "the submit response itself carries the new state"
        )
        assert is_valid_uuid(data["generated_order_id"]), (
            "the generated order id is present in the same response"
        )
        assert_route_stop(data)

    def test_posture_stays_active_one_below_capacity(self, api):
        """PRD §2.9: "when `on_hand_qty` plus `open_order_qty` reaches or
        exceeds `max_qty`, the agreement auto-transitions from `ACTIVE` to
        `AT_CAPACITY`; when the sum falls below `max_qty`, it auto-transitions
        from `AT_CAPACITY` back to `ACTIVE`."

        Design: Corner/cross_cutting_layers/posture_auto_transition_threshold_gating
        """
        ctx = setup_site_part_agreement(api, unit_price_cents=100,
                                        min_qty=10, max_qty=50)
        rs = setup_started_route_with_stop(
            api, ctx["site"]["id"], ctx["agreement"]["id"])
        submitted = submit_stop(api, rs["stop"]["id"], 49)
        assert submitted["generated_order_id"] is None, (
            "49 >= min 10, so no order is generated"
        )
        agr = get_success_data(
            api.get_bin_agreement(ctx["agreement"]["id"], ADMIN))
        assert agr["status"] == "ACTIVE", (
            "on_hand 49 + open 0 = 49 < max 50: one unit below the threshold "
            "keeps the agreement ACTIVE under the >= rule"
        )

    def test_derived_fields_reconcile_through_delivery_chain(self, api):
        """PRD §3.4: "A successful confirmation pins `delivery_mode` from the
        site, adds `ordered_qty` to the agreement's `open_order_qty`, adds
        `total_price_cents` to the site's `outstanding_balance_cents`,
        recomputes the agreement posture (which may flip it to `AT_CAPACITY`),
        and increments the `version` of the order, the agreement, and the site
        by one each."
        PRD §3.4: "Delivery by the `RouteDriver` moves `IN_TRANSIT` to
        `DELIVERED` and is the moment stock lands: the agreement's
        `on_hand_qty` increases by `ordered_qty`, its `open_order_qty`
        decreases by `ordered_qty`, and the site's `outstanding_balance_cents`
        decreases by `total_price_cents` — delivery settles the balance, since
        invoicing is out of scope."
        PRD §3.4: "The posture recompute that follows may restore
        `AT_CAPACITY` to `ACTIVE`, or leave the agreement at capacity when the
        on-hand figure alone already reaches `max_qty`."

        Design: Corner/cross_cutting_layers/derived_fields_reconcile_through_delivery_chain
        """
        ctx = setup_draft_order(api, counted_qty=5, min_qty=10, max_qty=100)
        agr_id = ctx["agreement"]["id"]
        order_id = ctx["order_id"]

        agr = get_success_data(api.get_bin_agreement(agr_id, ADMIN))
        assert agr["on_hand_qty"] == 5, "submit writes the count into on_hand"
        assert agr["open_order_qty"] == 0, "a DRAFT order is not yet open"

        get_success_data(api.confirm_order(order_id, ADMIN))
        agr = get_success_data(api.get_bin_agreement(agr_id, ADMIN))
        assert agr["open_order_qty"] == 95, "confirmation opens the ordered qty"

        get_success_data(api.ship_order(order_id, ADMIN))
        get_success_data(api.deliver_order(order_id, DRIVER))
        agr = get_success_data(api.get_bin_agreement(agr_id, ADMIN))
        assert agr["on_hand_qty"] == 100, "delivery lands 5 + 95 in the bin"
        assert agr["open_order_qty"] == 0
        assert agr["status"] == "AT_CAPACITY", (
            "on_hand 100 alone reaches max 100 after delivery"
        )


class TestCapacityCascadeDepth3:
    def test_submit_confirm_chain_flips_agreement_to_at_capacity(self, api):
        """PRD §3.4: "A successful confirmation pins `delivery_mode` from the
        site, adds `ordered_qty` to the agreement's `open_order_qty`, adds
        `total_price_cents` to the site's `outstanding_balance_cents`,
        recomputes the agreement posture (which may flip it to `AT_CAPACITY`),
        and increments the `version` of the order, the agreement, and the site
        by one each."
        PRD §2.9: "when `on_hand_qty` plus `open_order_qty` reaches or exceeds
        `max_qty`, the agreement auto-transitions from `ACTIVE` to
        `AT_CAPACITY`; when the sum falls below `max_qty`, it auto-transitions
        from `AT_CAPACITY` back to `ACTIVE`."

        Scan at 5 on max 100 creates order qty 95; confirmation opens 95, and
        5 + 95 = 100 >= 100 flips the agreement AT_CAPACITY.

        Design: Difficulty/transitive_cascade/stop_submit_to_order_to_capacity_posture_depth3
        """
        ctx = setup_draft_order(api, counted_qty=5, min_qty=10, max_qty=100)
        agr_id = ctx["agreement"]["id"]
        order_id = ctx["order_id"]

        agr = get_success_data(api.get_bin_agreement(agr_id, ADMIN))
        assert agr["status"] == "ACTIVE", "5 + 0 stays below max 100"

        confirmed = validate_success(api.confirm_order(order_id, ADMIN))
        assert confirmed["status"] == "CONFIRMED"
        agr = get_success_data(api.get_bin_agreement(agr_id, ADMIN))
        assert agr["open_order_qty"] == 95
        assert agr["status"] == "AT_CAPACITY", (
            "on_hand 5 + open 95 = 100 >= max 100 flips the posture"
        )

    def test_at_capacity_agreement_retire_blocked_by_confirmed_order(self, api):
        """PRD §3.7: "A `DistributorAdmin` retires a bin agreement from either
        `ACTIVE` or `AT_CAPACITY`; the system refuses while any order for the
        agreement remains in `DRAFT`, `CONFIRMED`, `ON_HOLD`, or `IN_TRANSIT`,
        and the transition increments the agreement's `version`."
        PRD §2.8: "transition legality — the target resource must be in a state
        from which the requested transition exists, surfacing
        `ERR_INVALID_STATE`".

        Design: Difficulty/transitive_cascade/stop_submit_to_order_to_capacity_posture_depth3
        """
        ctx = setup_confirmed_order(api, counted_qty=5, min_qty=10,
                                    max_qty=100)
        agr_id = ctx["agreement"]["id"]
        agr = get_success_data(api.get_bin_agreement(agr_id, ADMIN))
        assert agr["status"] == "AT_CAPACITY"
        resp = api.retire_bin_agreement(agr_id, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = get_success_data(api.get_bin_agreement(agr_id, ADMIN))
        assert after["status"] == "AT_CAPACITY", (
            "the capacity-flipped agreement survives the refused retirement"
        )


class TestForeignKeyReverseReachability:
    def test_fk_reverse_reachability_lists(self, api):
        """PRD §3.2: "Agreements are listable with `site_id`, `part_id`, and
        `status` filters."
        PRD §3.3: "Stops support reverse reachability: they are listable per
        route, and the stop listing also accepts `route_id`,
        `bin_agreement_id`, `generated_order_id`, and `status` filters, so
        operators can trace which stop produced a given order and which stops a
        given agreement has seen."
        PRD §3.4: "Orders are listable with `bin_agreement_id`, `site_id`,
        `part_id`, and `status` filters."

        Design: Corner/endpoints/fk_reverse_reachability_lists
        """
        ctx = setup_site_part_agreement(api, credit_limit_cents=100000,
                                        min_qty=1, max_qty=10)
        route = create_route(api, ctx["site"]["id"])
        stop = create_stop(api, route["id"], ctx["agreement"]["id"])

        agrs, meta = validate_paginated(
            api.list_bin_agreements(ADMIN,
                                    params={"site_id": ctx["site"]["id"]}))
        assert [a["id"] for a in agrs] == [ctx["agreement"]["id"]]
        assert meta["total_count"] == 1

        stops, meta = validate_paginated(
            api.list_route_stops(route["id"], DRIVER))
        assert [s["id"] for s in stops] == [stop["id"]]
        assert meta["total_count"] == 1

        orders, meta = validate_paginated(
            api.list_replenishment_orders(
                ADMIN, params={"bin_agreement_id": ctx["agreement"]["id"]}))
        assert orders == [], "no scan has produced an order yet"
        assert meta["total_count"] == 0
