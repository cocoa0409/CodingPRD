"""Delivery routes, delivery transit, cold-chain replay, and the service-unit
ledger (PRD §3.5, §2.10)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    assert_cold_chain_reading, assert_authorization_units_conserved,
    create_route_payload, create_delivery_payload,
    create_route, schedule_delivery, out_for_delivery, mark_delivered,
    mark_failed, add_reading, get_delivery, get_reauthorization,
    setup_frozen_cycle, setup_scheduled_delivery, setup_out_for_delivery,
    create_approved_authorization,
)

DIABETIC_RX = {
    "diet_type": "DIABETIC", "daily_sodium_mg_max": 2300,
    "daily_potassium_mg_max": 3000, "daily_phosphorus_mg_max": 1200,
    "daily_carbs_g_max": 200, "daily_protein_g_min": 30,
}


def _out_for_delivery_chicken(driver_id, route_date="2026-05-06",
                              week_start="2026-05-04", member_name="M Six",
                              payer_member_id="MA-600"):
    """MA member + DIABETIC prescription + Chicken Plate x7 FROZEN + APPROVED
    authorization + DISPATCHED route + delivery OUT_FOR_DELIVERY."""
    return setup_out_for_delivery(
        member_overrides={"full_name": member_name,
                          "payer_type": "MEDICARE_ADVANTAGE",
                          "payer_member_id": payer_member_id,
                          "income_fpl_percent": 200, "household_size": 1},
        prescription_overrides=dict(DIABETIC_RX),
        item_specs=(("chicken_plate", 7),),
        week_start_date=week_start,
        route_overrides={"driver_id": driver_id, "route_date": route_date})


class TestDeliveryParallelStatusDimensions:
    def test_excursion_does_not_block_mark_delivered(self, api, driver_headers):
        """PRD §3.5: "the delivery starts in `SCHEDULED` with
        `cold_chain_status` `INTACT` — two parallel state dimensions that evolve
        independently from here."
        PRD §3.5: "An `EXCURSION` does not block marking the delivery
        `DELIVERED`"

        Design: Difficulty/non_linear_state_machine/delivery_parallel_status_dimensions
        """
        ctx = _out_for_delivery_chicken("drv-3", route_date="2026-04-15",
                                        week_start="2026-04-13")
        d_id = ctx["delivery"]["id"]
        add_reading(d_id, "2026-04-15T09:00:00Z", 8.5)
        add_reading(d_id, "2026-04-15T09:10:00Z", 7.0)
        delivered = validate_success(api.mark_delivered(d_id, driver_headers))
        assert delivered["cumulative_excursion_minutes"] == 10, \
            "8.5C interval [09:00, 09:10] accrues 10 whole minutes"
        assert delivered["cold_chain_status"] == "EXCURSION"
        assert delivered["status"] == "DELIVERED"

    def test_delivery_completes_cycle_and_consumes_unit(self, api,
                                                        driver_headers):
        """PRD §3.5: "A successful delivery stamps `delivered_at` from the
        logical clock and settles the reserved unit: the authorization's
        `reserved_units` decreases by one and its `used_units` increases by one,
        with a `version` bump"
        PRD §3.5: "If the delivery's cycle now has all deliveries terminal with
        at least one `DELIVERED`, the cycle flips automatically to `FULFILLED`."

        Design: Difficulty/non_linear_state_machine/delivery_parallel_status_dimensions
        """
        ctx = _out_for_delivery_chicken("drv-3", route_date="2026-04-15",
                                        week_start="2026-04-13")
        d_id = ctx["delivery"]["id"]
        add_reading(d_id, "2026-04-15T09:00:00Z", 8.5)
        add_reading(d_id, "2026-04-15T09:10:00Z", 7.0)
        validate_success(api.mark_delivered(d_id, driver_headers))
        cycle = validate_success(
            api.get_menu_cycle(ctx["cycle"]["id"], driver_headers))
        assert cycle["status"] == "FULFILLED"
        auth = get_reauthorization(ctx["authorization"]["id"])
        assert auth["reserved_units"] == 0
        assert auth["used_units"] == 1


class TestColdChainSpoilageCascade:
    def _setup(self):
        ctx = setup_out_for_delivery(
            member_overrides={"full_name": "M Eight", "payer_member_id": "W-800"},
            route_overrides={"driver_id": "drv-5"})
        add_reading(ctx["delivery"]["id"], "2026-05-06T09:00:00Z", 7.0)
        return ctx

    def test_spoilage_flips_both_delivery_dimensions(self, api):
        """PRD §3.5: "`SPOILED` when cumulative excursion is strictly greater
        than 30 minutes — exactly 30 is not spoiled."
        PRD §3.5: "a transition of `cold_chain_status` to `SPOILED` forces the
        delivery's own `status` to `SPOILED` and releases its reserved unit with
        the usual authorization `version` bump."

        Design: Difficulty/transitive_cascade/cold_chain_spoilage_depth2_cascade
        """
        ctx = self._setup()
        d_id = ctx["delivery"]["id"]
        add_reading(d_id, "2026-05-06T09:10:00Z", 9.0)
        add_reading(d_id, "2026-05-06T09:45:00Z", 7.5)
        delivery = get_delivery(d_id)
        assert delivery["cumulative_excursion_minutes"] == 35, \
            "9.0C interval [09:10, 09:45] accrues 35 minutes"
        assert delivery["cold_chain_status"] == "SPOILED"
        assert delivery["status"] == "SPOILED", \
            "link 1: cold-chain SPOILED forces the transit status to SPOILED"

    def test_spoilage_releases_reserved_unit(self, api):
        """PRD §3.5: "a transition of `cold_chain_status` to `SPOILED` forces
        the delivery's own `status` to `SPOILED` and releases its reserved unit
        with the usual authorization `version` bump."

        Design: Difficulty/transitive_cascade/cold_chain_spoilage_depth2_cascade
        """
        ctx = self._setup()
        d_id = ctx["delivery"]["id"]
        add_reading(d_id, "2026-05-06T09:10:00Z", 9.0)
        add_reading(d_id, "2026-05-06T09:45:00Z", 7.5)
        auth = get_reauthorization(ctx["authorization"]["id"])
        assert auth["reserved_units"] == 0, \
            "link 2: the SPOILED mutation releases the reserved unit"
        assert auth["used_units"] == 0
        assert auth["available_units"] == 4


class TestColdChainSpoilageBoundary:
    def _setup_at_30_minutes(self):
        """Delivery OUT_FOR_DELIVERY accumulated to exactly 30 excursion
        minutes: 09:00 7.0C, 09:10 8.5C, 09:40 7.0C."""
        ctx = _out_for_delivery_chicken("drv-8", member_name="M Twelve",
                                        payer_member_id="MA-220")
        d_id = ctx["delivery"]["id"]
        add_reading(d_id, "2026-05-06T09:00:00Z", 7.0)
        add_reading(d_id, "2026-05-06T09:10:00Z", 8.5)
        add_reading(d_id, "2026-05-06T09:40:00Z", 7.0)
        return ctx

    def test_exactly_30_minutes_is_not_spoiled(self, api):
        """PRD §3.5: "`EXCURSION` when at least one does but cumulative
        excursion is at most 30 minutes; `SPOILED` when cumulative excursion is
        strictly greater than 30 minutes — exactly 30 is not spoiled."

        Design: Difficulty/boundary_precision_check/cold_chain_exactly_30_minutes_not_spoiled
        """
        ctx = self._setup_at_30_minutes()
        delivery = get_delivery(ctx["delivery"]["id"])
        assert delivery["cumulative_excursion_minutes"] == 30
        assert delivery["cold_chain_status"] == "EXCURSION"
        assert delivery["status"] == "OUT_FOR_DELIVERY"

    def test_31st_minute_spoils_and_releases_unit(self, api):
        """PRD §3.5: "`SPOILED` when cumulative excursion is strictly greater
        than 30 minutes — exactly 30 is not spoiled."
        PRD §3.5: "a transition of `cold_chain_status` to `SPOILED` forces the
        delivery's own `status` to `SPOILED` and releases its reserved unit with
        the usual authorization `version` bump."

        Design: Difficulty/boundary_precision_check/cold_chain_exactly_30_minutes_not_spoiled
        """
        ctx = self._setup_at_30_minutes()
        d_id = ctx["delivery"]["id"]
        add_reading(d_id, "2026-05-06T09:50:00Z", 8.6)
        add_reading(d_id, "2026-05-06T09:51:00Z", 7.2)
        delivery = get_delivery(d_id)
        assert delivery["cumulative_excursion_minutes"] == 31
        assert delivery["cold_chain_status"] == "SPOILED"
        assert delivery["status"] == "SPOILED"
        auth = get_reauthorization(ctx["authorization"]["id"])
        assert auth["reserved_units"] == 0


class TestRouteWindowOverlap:
    def test_adjacent_half_open_windows_allowed(
            self, api, logistics_coordinator_headers):
        """PRD §3.5: "For the same driver on the same date, windows of
        non-terminal routes must not overlap under half-open semantics —
        back-to-back windows that merely touch are allowed, since the end
        boundary is exclusive — and a colliding route is rejected with
        `ERR_ROUTE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/route_window_half_open_adjacency
        """
        r1 = create_route(driver_id="drv-x", route_date="2026-05-06",
                          start_time="08:00", end_time="12:00")
        assert r1["status"] == "PLANNED"
        resp = api.create_route(create_route_payload(
            driver_id="drv-x", route_date="2026-05-06",
            start_time="12:00", end_time="14:00", capacity_stops=10),
            logistics_coordinator_headers)
        r2 = validate_success(resp, 201)
        assert r2["status"] == "PLANNED", \
            "12:00 start touches but does not overlap the half-open [08:00, 12:00)"

    def test_interior_overlap_rejected(self, api, logistics_coordinator_headers):
        """PRD §3.5: "For the same driver on the same date, windows of
        non-terminal routes must not overlap under half-open semantics —
        back-to-back windows that merely touch are allowed, since the end
        boundary is exclusive — and a colliding route is rejected with
        `ERR_ROUTE_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/route_window_half_open_adjacency
        """
        create_route(driver_id="drv-x", route_date="2026-05-06",
                     start_time="08:00", end_time="12:00")
        resp = api.create_route(create_route_payload(
            driver_id="drv-x", route_date="2026-05-06",
            start_time="11:00", end_time="13:00", capacity_stops=10),
            logistics_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_ROUTE_WINDOW_OVERLAP)


class TestUnitReserveReleaseInvariant:
    def _setup(self):
        return setup_out_for_delivery(
            member_overrides={"full_name": "M Sixteen",
                              "payer_member_id": "W-610"},
            route_overrides={"driver_id": "drv-11"})

    def test_mark_failed_releases_reserved_unit_exactly(self, api,
                                                        driver_headers):
        """PRD §3.5: "Marking a delivery failed — again only from
        `OUT_FOR_DELIVERY` — performs the compensating release: `reserved_units`
        decreases by one (with a `version` bump), no unit is consumed, and the
        same automatic cycle-fulfillment check runs."

        Design: Difficulty/compensating_invariant/authorization_unit_reserve_release_invariant
        """
        ctx = self._setup()
        auth_before = get_reauthorization(ctx["authorization"]["id"])
        assert auth_before["reserved_units"] == 1
        assert auth_before["available_units"] == 3
        failed = validate_success(api.mark_failed(ctx["delivery"]["id"],
                                                  driver_headers))
        assert failed["status"] == "FAILED"
        auth = get_reauthorization(ctx["authorization"]["id"])
        assert auth["used_units"] == 0
        assert auth["reserved_units"] == 0
        assert auth["available_units"] == 4, \
            "reserve-then-fail must restore the pre-schedule buckets exactly"

    def test_unit_conservation_holds_across_reserve_and_compensate(
            self, api, driver_headers):
        """PRD §2.10: "First, on every reauthorization, the number of
        authorized service units always equals the sum of used, reserved, and
        available units — deliveries move units between those buckets but never
        create or destroy them."

        Design: Difficulty/compensating_invariant/authorization_unit_reserve_release_invariant
        """
        ctx = self._setup()
        auth_reserved = get_reauthorization(ctx["authorization"]["id"])
        assert_authorization_units_conserved(auth_reserved)
        validate_success(api.mark_failed(ctx["delivery"]["id"], driver_headers))
        auth_released = get_reauthorization(ctx["authorization"]["id"])
        assert_authorization_units_conserved(auth_released)
        assert auth_released["authorized_units"] == 4
        assert auth_released["used_units"] == 0
        assert auth_released["reserved_units"] == 0
        assert auth_released["available_units"] == 4


class TestRouteCompletionGuard:
    def test_route_complete_with_open_delivery_rejected(
            self, api, logistics_coordinator_headers):
        """PRD §3.5: "Completion moves a `DISPATCHED` route to `COMPLETED`, but
        only once every delivery on the route has reached a terminal state; open
        deliveries block completion with `ERR_ROUTE_HAS_OPEN_DELIVERIES`"

        Design: Corner/state_machines/route_complete_with_open_delivery_rejected
        """
        ctx = setup_scheduled_delivery(
            member_overrides={"full_name": "S Six", "payer_member_id": "W-S6"},
            route_overrides={"driver_id": "drv-s6"})
        resp = api.complete_route(ctx["route"]["id"],
                                  logistics_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_ROUTE_HAS_OPEN_DELIVERIES)
        route = validate_success(
            api.get_route(ctx["route"]["id"], logistics_coordinator_headers))
        assert route["status"] == "DISPATCHED"


class TestDeliveryTransitGuards:
    def test_mark_delivered_from_scheduled_rejected(self, api, driver_headers):
        """PRD §3.5: "Marking it delivered requires `OUT_FOR_DELIVERY`
        (otherwise `ERR_DELIVERY_NOT_OUT_FOR_DELIVERY`)"

        Design: Corner/state_machines/delivery_mark_delivered_from_scheduled_rejected
        """
        ctx = setup_scheduled_delivery(
            member_overrides={"full_name": "S Five", "payer_member_id": "W-S5"},
            route_overrides={"driver_id": "drv-s5"})
        resp = api.mark_delivered(ctx["delivery"]["id"], driver_headers)
        validate_error(resp, ApiErrorId.ERR_DELIVERY_NOT_OUT_FOR_DELIVERY)
        delivery = get_delivery(ctx["delivery"]["id"])
        assert delivery["status"] == "SCHEDULED"
        auth = get_reauthorization(ctx["authorization"]["id"])
        assert auth["used_units"] == 0
        assert auth["reserved_units"] == 1


class TestColdChainChronologicalReplay:
    def test_out_of_order_insertion_replayed_sorted(self, api):
        """PRD §3.5: "After every inserted reading the server replays the
        delivery's readings sorted by `recorded_at` ascending with ties broken
        by `created_at` ascending — insertion order may differ from recorded
        order, and the sorted order governs."
        PRD §3.5: "`EXCURSION` when at least one does but cumulative excursion
        is at most 30 minutes"

        Design: Corner/calculations/cold_chain_chronological_replay_out_of_order
        """
        ctx = _out_for_delivery_chicken("drv-k1", member_name="K One",
                                        payer_member_id="MA-K1")
        d_id = ctx["delivery"]["id"]
        add_reading(d_id, "2026-05-06T09:40:00Z", 7.0)
        add_reading(d_id, "2026-05-06T09:10:00Z", 8.5)
        add_reading(d_id, "2026-05-06T09:00:00Z", 7.0)
        delivery = get_delivery(d_id)
        assert delivery["cumulative_excursion_minutes"] == 30, \
            "sorted replay puts the 8.5C reading at [09:10, 09:40] = 30 minutes"
        assert delivery["cold_chain_status"] == "EXCURSION"
        assert delivery["status"] == "OUT_FOR_DELIVERY"


class TestColdChainReadingShape:
    def test_reading_is_append_only_without_version_or_updated_at(
            self, api, driver_headers):
        """PRD §2.5: "a **MenuCycleItem** line and a **ColdChainReading** carry
        only `id` and `created_at`. Both `updated_at` and `version` are absent
        from these two resources, because neither is ever mutated after
        insertion."

        Design: Corner/entities/cold_chain_reading_immutable_common_fields_false
        """
        ctx = setup_out_for_delivery(
            member_overrides={"full_name": "C Four", "payer_member_id": "W-C4"},
            route_overrides={"driver_id": "drv-c4"})
        resp = api.add_cold_chain_reading(
            ctx["delivery"]["id"],
            {"recorded_at": "2026-05-06T09:00:00Z", "temp_celsius": 7.0},
            driver_headers)
        reading = validate_success(resp, 201)
        assert reading["temp_celsius"] == 7.0
        assert_cold_chain_reading(reading)


class TestDeliverySchedulingTemporalRules:
    def test_service_date_outside_authorization_window(
            self, api, logistics_coordinator_headers):
        """PRD §3.5: "If no approved authorization's window covers the service
        date at all, scheduling is rejected with
        `ERR_SERVICE_DATE_OUT_OF_AUTHORIZATION`"

        Design: Corner/validations/delivery_service_date_outside_authorization_window
        """
        ctx = setup_frozen_cycle(
            member_overrides={"full_name": "V Two", "payer_member_id": "W-V2"})
        auth = create_approved_authorization(
            ctx["member"]["id"], authorization_number="AUTH-V2",
            start_date="2026-06-01", end_date="2026-12-31")
        route = create_route(dispatch=True, driver_id="drv-v2",
                             route_date="2026-05-06")
        resp = api.create_delivery(
            create_delivery_payload(ctx["member"]["id"], ctx["cycle"]["id"],
                                    route["id"], service_date="2026-05-06"),
            logistics_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_SERVICE_DATE_OUT_OF_AUTHORIZATION)
        auth_after = get_reauthorization(auth["id"])
        assert auth_after["reserved_units"] == 0, \
            "a rejected schedule must not reserve a unit"


class TestDeliveryFiltering:
    def test_deliveries_filtered_by_menu_cycle_reverse_reachable(
            self, api, logistics_coordinator_headers):
        """PRD §2.3: "deliveries by `member_id`, `menu_cycle_id`, `route_id`,
        `authorization_id`, and `status`"
        PRD §3.5: "On success the selected authorization's `reserved_units`
        increases by one (bumping its `version`), the delivery records the
        winning `authorization_id`, and the delivery starts in `SCHEDULED`"

        Design: Corner/endpoints/deliveries_filtered_by_menu_cycle_reverse_reachable
        """
        ctx = setup_scheduled_delivery(
            member_overrides={"full_name": "E One", "payer_member_id": "W-E1"},
            route_overrides={"driver_id": "drv-e1"})
        resp = api.list_deliveries(logistics_coordinator_headers,
                                   params={"menu_cycle_id": ctx["cycle"]["id"]})
        data, _meta = validate_paginated(resp)
        assert len(data) == 1
        assert data[0]["id"] == ctx["delivery"]["id"]
        assert data[0]["menu_cycle_id"] == ctx["cycle"]["id"]
        assert data[0]["authorization_id"] == ctx["authorization"]["id"]
