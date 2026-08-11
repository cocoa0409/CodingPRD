"""Carrier routes and consolidation totes: membership guards, capacity
bounds, seal/unseal cycle, dispatch gating, discrepancy/reconcile loop, and
the manifest add/remove conservation invariant."""
from test_helpers import (
    ApiErrorId,
    add_order_to_tote,
    create_counter_order_dropped_off,
    create_location,
    create_return_item_line,
    create_route,
    make_location_operator_headers,
    setup_commercial_spine,
    setup_tote_with_route,
    tote_membership_payload,
    flag_discrepancy_payload,
    validate_error,
    validate_success,
)


def _counter_spine(email):
    return setup_commercial_spine(
        plan_overrides={"pickup_enabled": False}, shopper_email=email
    )


def _dropped_order(spine, location, sku, **line_overrides):
    return create_counter_order_dropped_off(
        spine, location,
        items=[create_return_item_line(sku=sku, **line_overrides)],
    )


class TestToteCreation:

    def test_error_route_origin_mismatch_on_tote_create(self, api):
        """PRD §3.7: "the tote's `location_id` must equal the route's
        `origin_location_id`, else `ERR_ROUTE_ORIGIN_MISMATCH`."

        Design: Corner/errors/error_route_origin_mismatch_on_tote_create
        """
        from test_helpers import create_consolidation_tote_payload
        location_a = create_location(name="L-OA", kind="COUNTER")
        location_b = create_location(name="L-OB", kind="COUNTER")
        route = create_route(location_a["id"])
        resp = api.create_consolidation_tote(
            create_consolidation_tote_payload(route["id"], location_b["id"]),
            make_location_operator_headers(location_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_ORIGIN_MISMATCH)


class TestToteMembership:

    def test_tote_add_order_not_dropped_off_rejected(self, api):
        """PRD §3.7: "only for orders that are `DROPPED_OFF` at the tote's own
        location".
        PRD §2.8: "the target resource is in a valid from-state for the
        requested transition and terminal resources reject everything, else
        `ERR_INVALID_STATE` or `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/tote_add_order_not_dropped_off_rejected
        """
        from test_helpers import create_order
        spine = _counter_spine("snd@x.com")
        location = create_location(name="L-ND", kind="COUNTER")
        route, tote = setup_tote_with_route(location)
        order = create_order(spine, method="COUNTER_DROP")  # stays INITIATED
        resp = api.add_order_to_tote(
            tote["id"],
            tote_membership_payload(order["id"], tote["version"]),
            make_location_operator_headers(location["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_tote_add_order_from_other_location_rejected(self, api):
        """PRD §3.7: "an order whose `dropoff_location_id` differs is rejected
        with `ERR_ORDER_NOT_AT_LOCATION`".

        Design: Corner/state_machines/tote_add_order_from_other_location_rejected
        """
        spine = _counter_spine("sxl@x.com")
        location_a = create_location(name="L-A", kind="COUNTER")
        location_b = create_location(name="L-B", kind="COUNTER")
        route, tote = setup_tote_with_route(location_b)
        order = _dropped_order(spine, location_a, "XL2")
        resp = api.add_order_to_tote(
            tote["id"],
            tote_membership_payload(order["id"], tote["version"]),
            make_location_operator_headers(location_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_AT_LOCATION)

    def test_tote_membership_change_when_sealed_rejected(self, api):
        """PRD §3.7: "Structurally, only a `FILLING` tote accepts adds or
        removes — otherwise `ERR_TOTE_NOT_FILLING`".

        Design: Corner/state_machines/tote_membership_change_when_sealed_rejected
        """
        from test_helpers import api_client
        spine = _counter_spine("snf@x.com")
        location = create_location(name="L-NF", kind="COUNTER")
        route, tote = setup_tote_with_route(location)
        order1 = _dropped_order(spine, location, "N1")
        order2 = _dropped_order(spine, location, "N2")

        tote = add_order_to_tote(tote, order1, location["id"])
        # Seal bumps the tote version; capture the fresh version so the OCC
        # check (§2.8 P5) passes and the FILLING rule (P11) is what fires.
        tote = validate_success(
            api_client.seal_tote(tote["id"],
                                 make_location_operator_headers(location["id"]))
        )
        resp = api.add_order_to_tote(
            tote["id"],
            tote_membership_payload(order2["id"], tote["version"]),
            make_location_operator_headers(location["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TOTE_NOT_FILLING)

    def test_error_order_already_in_tote(self, api):
        """PRD §3.7: "an order already holding a tote membership anywhere is
        rejected with `ERR_ORDER_ALREADY_IN_TOTE`."

        Design: Corner/errors/error_order_already_in_tote
        """
        spine = _counter_spine("sai@x.com")
        location = create_location(name="L-AI", kind="COUNTER")
        route, tote = setup_tote_with_route(location)
        order = _dropped_order(spine, location, "AI")
        tote = add_order_to_tote(tote, order, location["id"])
        resp = api.add_order_to_tote(
            tote["id"],
            tote_membership_payload(order["id"], tote["version"]),
            make_location_operator_headers(location["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_ALREADY_IN_TOTE)


class TestToteCapacity:

    def test_tote_weight_exact_30000_allowed_30001_rejected(self, api):
        """PRD §3.7: "An add is rejected with `ERR_TOTE_CAPACITY_EXCEEDED`
        when it would push the unit total strictly beyond 40, and with
        `ERR_TOTE_WEIGHT_EXCEEDED` when it would push the weight strictly
        beyond 30,000 grams; landing exactly on either bound is allowed."

        Design: Difficulty/boundary_precision_check/tote_weight_exact_30000_allowed_30001_rejected
        """
        spine = _counter_spine("sw@x.com")
        location = create_location(name="L-W", kind="COUNTER")
        route, tote = setup_tote_with_route(location)

        order1 = _dropped_order(spine, location, "W1", weight_grams=10000,
                                longest_side_cm=20)
        order2 = _dropped_order(spine, location, "W2", weight_grams=10000,
                                longest_side_cm=20)
        order3 = _dropped_order(spine, location, "W3", weight_grams=10000,
                                longest_side_cm=20)
        order4 = _dropped_order(spine, location, "W4", weight_grams=1,
                                longest_side_cm=20)

        tote = add_order_to_tote(tote, order1, location["id"])
        tote = add_order_to_tote(tote, order2, location["id"])
        tote = add_order_to_tote(tote, order3, location["id"])
        assert tote["manifest_weight_grams"] == 30000

        resp = api.add_order_to_tote(
            tote["id"],
            tote_membership_payload(order4["id"], tote["version"]),
            make_location_operator_headers(location["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TOTE_WEIGHT_EXCEEDED)

    def test_error_tote_unit_capacity_boundary(self, api):
        """PRD §3.7: "An add is rejected with `ERR_TOTE_CAPACITY_EXCEEDED`
        when it would push the unit total strictly beyond 40, and with
        `ERR_TOTE_WEIGHT_EXCEEDED` when it would push the weight strictly
        beyond 30,000 grams; landing exactly on either bound is allowed."

        Design: Corner/errors/error_tote_unit_capacity_boundary
        """
        spine = _counter_spine("stu@x.com")
        location = create_location(name="L-TU", kind="COUNTER")
        route, tote = setup_tote_with_route(location)

        big = _dropped_order(spine, location, "BIG", quantity=40,
                             unit_price_cents=10, weight_grams=50)
        small = _dropped_order(spine, location, "SML", quantity=1,
                               unit_price_cents=10, weight_grams=50)

        tote = add_order_to_tote(tote, big, location["id"])
        assert tote["manifest_units"] == 40

        resp = api.add_order_to_tote(
            tote["id"],
            tote_membership_payload(small["id"], tote["version"]),
            make_location_operator_headers(location["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_TOTE_CAPACITY_EXCEEDED)


class TestToteManifestInvariant:

    def test_tote_add_remove_conserves_manifest_totals(self, api):
        """PRD §3.7: "A successful add sets the order's `tote_id`, a remove
        clears it back to null, and either operation recomputes the manifest
        totals and increments the tote's `version` by one."

        Design: Difficulty/compensating_invariant/tote_add_remove_conserves_manifest_totals
        """
        from test_helpers import api_client
        spine = _counter_spine("siv@x.com")
        location = create_location(name="L-I", kind="COUNTER")
        route, tote = setup_tote_with_route(location)
        assert tote["manifest_units"] == 0
        assert tote["manifest_weight_grams"] == 0

        order = _dropped_order(spine, location, "IV", quantity=2,
                               weight_grams=800, longest_side_cm=20)

        tote_mid = add_order_to_tote(tote, order, location["id"])
        assert tote_mid["manifest_units"] == 2
        assert tote_mid["manifest_weight_grams"] == 1600

        tote_post = validate_success(
            api_client.remove_order_from_tote(
                tote["id"],
                tote_membership_payload(order["id"], tote_mid["version"]),
                make_location_operator_headers(location["id"]),
            )
        )
        assert tote_post["manifest_units"] == 0
        assert tote_post["manifest_weight_grams"] == 0
        assert tote_post["version"] == tote["version"] + 2

        order_after = validate_success(
            api_client.get_return_order(
                order["id"], make_location_operator_headers(location["id"])
            )
        )
        assert order_after["tote_id"] is None

    def test_tote_add_response_reflects_manifest_immediately(self, api):
        """PRD §2.10: "each cascade is atomic with its trigger: a reader never
        observes a partially applied cascade".
        PRD §3.7: "either operation recomputes the manifest totals and
        increments the tote's `version` by one."

        Design: Corner/consistency_model/tote_add_response_reflects_manifest_immediately
        """
        spine = _counter_spine("sic@x.com")
        location = create_location(name="L-IC", kind="COUNTER")
        route, tote = setup_tote_with_route(location)
        order = _dropped_order(spine, location, "IC", quantity=2,
                               weight_grams=800)
        tote_after = add_order_to_tote(tote, order, location["id"])
        # The add response itself carries the recomputed manifest totals.
        assert tote_after["manifest_units"] == 2
        assert tote_after["manifest_weight_grams"] == 1600


class TestSealDispatch:

    def test_seal_empty_tote_rejected(self, api):
        """PRD §3.7: "The operator seals a `FILLING` tote that holds at least
        one unit — sealing an empty tote is refused with `ERR_TOTE_EMPTY`".

        Design: Corner/state_machines/seal_empty_tote_rejected
        """
        from test_helpers import api_client
        location = create_location(name="L-ES", kind="COUNTER")
        route, tote = setup_tote_with_route(location)
        resp = api_client.seal_tote(
            tote["id"], make_location_operator_headers(location["id"])
        )
        validate_error(resp, ApiErrorId.ERR_TOTE_EMPTY)

    def test_tote_dispatch_requires_route_dispatched(self, api):
        """PRD §3.7: "Dispatching a `SEALED` tote requires its route already
        `DISPATCHED`, else `ERR_ROUTE_NOT_DISPATCHED`". "dispatch moves the
        tote to `DISPATCHED` and every member order from `DROPPED_OFF` to
        `IN_TRANSIT`."

        Design: Difficulty/cross_entity_state_dependency/tote_dispatch_requires_route_dispatched
        """
        from test_helpers import TEST_USERS, api_client
        spine = _counter_spine("srd@x.com")
        location = create_location(name="L-RD", kind="COUNTER")
        route, tote = setup_tote_with_route(location)
        order = _dropped_order(spine, location, "RD")
        tote = add_order_to_tote(tote, order, location["id"])
        validate_success(
            api_client.seal_tote(tote["id"],
                                 make_location_operator_headers(location["id"]))
        )

        # Route still PLANNED: tote dispatch rejected.
        blocked = api_client.dispatch_tote(
            tote["id"], make_location_operator_headers(location["id"])
        )
        validate_error(blocked, ApiErrorId.ERR_ROUTE_NOT_DISPATCHED)

        validate_success(
            api_client.dispatch_route(
                route["id"], TEST_USERS["carrier_dispatcher_headers"]
            )
        )
        dispatched = validate_success(
            api_client.dispatch_tote(
                tote["id"], make_location_operator_headers(location["id"])
            )
        )
        assert dispatched["status"] == "DISPATCHED"
        order_after = validate_success(
            api_client.get_return_order(
                order["id"], TEST_USERS["platform_admin_headers"]
            )
        )
        assert order_after["status"] == "IN_TRANSIT"

    def test_tote_dispatch_over_route_weight_rejected(self, api):
        """PRD §3.7: "Dispatching a `SEALED` tote requires its route already
        `DISPATCHED`, else `ERR_ROUTE_NOT_DISPATCHED`, and requires the tote's
        `manifest_weight_grams` not to exceed the route's
        `weight_capacity_grams`, else `ERR_ROUTE_WEIGHT_EXCEEDED`".

        Design: Corner/state_machines/tote_dispatch_over_route_weight_rejected
        """
        from test_helpers import TEST_USERS, api_client
        spine = _counter_spine("srw@x.com")
        location = create_location(name="L-RW", kind="COUNTER")
        route, tote = setup_tote_with_route(
            location, route_overrides={"weight_capacity_grams": 2000}
        )
        order = _dropped_order(spine, location, "RW", weight_grams=2500,
                               longest_side_cm=20)
        tote = add_order_to_tote(tote, order, location["id"])
        validate_success(
            api_client.seal_tote(tote["id"],
                                 make_location_operator_headers(location["id"]))
        )
        validate_success(
            api_client.dispatch_route(
                route["id"], TEST_USERS["carrier_dispatcher_headers"]
            )
        )
        resp = api_client.dispatch_tote(
            tote["id"], make_location_operator_headers(location["id"])
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_WEIGHT_EXCEEDED)

    def test_route_cancel_with_sealed_tote_rejected(self, api):
        """PRD §3.7: "Cancellation is refused with `ERR_ROUTE_HAS_LIVE_TOTE`
        when any tote in `SEALED` or `DISPATCHED` references the route".

        Design: Corner/state_machines/route_cancel_with_sealed_tote_rejected
        """
        from test_helpers import TEST_USERS, api_client
        spine = _counter_spine("src@x.com")
        location = create_location(name="L-RC", kind="COUNTER")
        route, tote = setup_tote_with_route(location)
        order = _dropped_order(spine, location, "RC")
        tote = add_order_to_tote(tote, order, location["id"])
        validate_success(
            api_client.seal_tote(tote["id"],
                                 make_location_operator_headers(location["id"]))
        )
        resp = api_client.cancel_route(
            route["id"], TEST_USERS["carrier_dispatcher_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_ROUTE_HAS_LIVE_TOTE)


class TestToteCycles:

    def test_tote_seal_unseal_discrepancy_cycles(self, api):
        """PRD §3.7: "the seal can be deliberately reverted, moving `SEALED`
        back to `FILLING` and clearing `sealed_by_user_id`, a cyclic pair that
        allows repacking before dispatch."
        PRD §3.7: "a `SupportAgent` or `PlatformAdmin` flags the tote with a
        `note`, moving `ARRIVED` → `DISCREPANCY`; reconciliation by a
        `SupportAgent` or the operator moves either `ARRIVED` or
        `DISCREPANCY` to the terminal `RECONCILED`, closing the audit loop."

        Design: Difficulty/non_linear_state_machine/tote_seal_unseal_discrepancy_cycles
        """
        from test_helpers import TEST_USERS, api_client
        spine = _counter_spine("so@x.com")
        location = create_location(name="L-Tote", kind="COUNTER")
        route, tote = setup_tote_with_route(location)
        order1 = _dropped_order(spine, location, "T1", weight_grams=500,
                                longest_side_cm=30)
        order2 = _dropped_order(spine, location, "T2", quantity=2,
                                unit_price_cents=700, weight_grams=400,
                                longest_side_cm=30)

        op = make_location_operator_headers(location["id"])
        tote = add_order_to_tote(tote, order1, location["id"])
        sealed = validate_success(api_client.seal_tote(tote["id"], op))
        assert sealed["sealed_by_user_id"] == location["id"]

        unsealed = validate_success(api_client.unseal_tote(tote["id"], op))
        assert unsealed["status"] == "FILLING"
        assert unsealed["sealed_by_user_id"] is None

        # The cyclic revert permits further membership change.
        tote = add_order_to_tote(unsealed, order2, location["id"])
        assert tote["manifest_units"] == 3

        validate_success(api_client.seal_tote(tote["id"], op))
        validate_success(
            api_client.dispatch_route(
                route["id"], TEST_USERS["carrier_dispatcher_headers"]
            )
        )
        validate_success(api_client.dispatch_tote(tote["id"], op))
        validate_success(
            api_client.arrive_tote(
                tote["id"], TEST_USERS["carrier_dispatcher_headers"]
            )
        )

        flagged = validate_success(
            api_client.flag_tote_discrepancy(
                tote["id"], flag_discrepancy_payload(),
                TEST_USERS["support_agent_headers"],
            )
        )
        assert flagged["status"] == "DISCREPANCY"
        reconciled = validate_success(
            api_client.reconcile_tote(
                tote["id"], TEST_USERS["support_agent_headers"]
            )
        )
        assert reconciled["status"] == "RECONCILED"

        # Members arrived into INSPECTING through the dispatch/arrive cascades.
        for order in (order1, order2):
            snapshot = validate_success(
                api_client.get_return_order(
                    order["id"], TEST_USERS["platform_admin_headers"]
                )
            )
            assert snapshot["status"] == "INSPECTING"
