"""Inventory availability, oversell ceilings, group/transient cascades, and KPIs.

Covers the availability calculation, the pickup forecast, the oversell-ceiling
boundary and exceed paths, aggregate/temporal overlap, the commit -> availability
-> KPI cascade, compensating inventory invariants, and the transient-reservation
consume/restore cycle.
"""
from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    set_clock,
    create_property,
    create_room_type,
    create_rate_plan,
    create_inventory_day,
    create_rate_decision,
    publish_decision,
    create_group_block,
    evaluate_group_block,
    commit_group_block,
    create_transient_reservation,
    confirm_reservation,
    ApiErrorId,
)

RM = TEST_USERS["revenue_manager_headers"]
GSM = TEST_USERS["group_sales_manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]


class TestAvailabilityAndForecast:
    def test_oversell_ceiling_floor_applied_to_availability(self, api):
        """PRD §2.7: "For any given night, the oversell ceiling is the night's
        `physical_capacity` multiplied by the quantity one plus the property's
        `overbooking_limit_pct`, with the result floored to a whole number of
        rooms."

        Design: Corner/calculations/availability_oversell_ceiling_floor_applied
        """
        prop = create_property(name="OverFloor", total_rooms=10, overbooking_limit_pct=0.10)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=10)
        inv = create_inventory_day(rt["id"], "2026-06-06T00:00:00Z", physical_capacity=10, transient_sold_rooms=9)
        data = validate_success(api.get_inventory_day(inv["id"], RM))
        # ceiling floor(10*1.10)=11; rooms_sold 9; available 2
        assert data["rooms_sold"] == 9
        assert data["rooms_available"] == 2, f"expected 2 got {data['rooms_available']}"

    def test_forecast_snapshot_pace(self, api):
        """PRD §3.3: "Under the default **SNAPSHOT_PACE** variant (selected when
        `method` is omitted or set to `SNAPSHOT_PACE`), the projected final sold
        count is the night's current `transient_sold_rooms` multiplied by a
        booking-curve pace factor of 1.5, with days-to-arrival ignored."

        Design: Corner/calculations/forecast_snapshot_pace_correct_result
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="FcastA", total_rooms=30)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=30)
        inv = create_inventory_day(rt["id"], "2026-06-06T00:00:00Z", physical_capacity=30, transient_sold_rooms=8)
        data = validate_success(api.forecast_inventory_day(inv["id"], ANALYST, params={"method": "SNAPSHOT_PACE"}))
        # round(8*1.5)=12; occ round(12/30,4)=0.4
        assert data["forecast_final_sold"] == 12, f"expected 12 got {data['forecast_final_sold']}"
        assert data["forecast_occupancy_pct"] == 0.4, f"expected 0.4 got {data['forecast_occupancy_pct']}"

    def test_forecast_trailing_pickup_uses_days_to_arrival(self, api):
        """PRD §3.3: "Under the **TRAILING_PICKUP** variant (selected when `method`
        is `TRAILING_PICKUP`), the projection instead adds a fixed trailing daily
        pickup of 2 rooms for each remaining day before arrival, ignoring the pace
        factor; the remaining days are the number of whole days between the logical
        clock's current date and the `stay_date`, never less than zero."

        Design: Corner/calculations/forecast_trailing_pickup_uses_days_to_arrival
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="FcastB", total_rooms=30)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=30)
        inv = create_inventory_day(rt["id"], "2026-06-06T00:00:00Z", physical_capacity=30, transient_sold_rooms=8)
        data = validate_success(api.forecast_inventory_day(inv["id"], ANALYST, params={"method": "TRAILING_PICKUP"}))
        # 8 + 2*5 = 18; occ round(18/30,4)=0.6
        assert data["forecast_final_sold"] == 18, f"expected 18 got {data['forecast_final_sold']}"
        assert data["forecast_occupancy_pct"] == 0.6, f"expected 0.6 got {data['forecast_occupancy_pct']}"


class TestOversellBoundary:
    def test_commit_exactly_fills_ceiling_succeeds(self, api):
        """PRD §2.7: "For any given night, the oversell ceiling is the night's
        `physical_capacity` multiplied by the quantity one plus the property's
        `overbooking_limit_pct`, with the result floored to a whole number of
        rooms."
        PRD §3.7: "for every night the night's `rooms_available` after the oversell
        ceiling must be at least the block's `rooms_per_night`, otherwise the
        commit is rejected with `ERR_OVERSELL_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/group_commit_exactly_fills_oversell_ceiling
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="BoundaryB", total_rooms=10, overbooking_limit_pct=0.10)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=10)
        inv = create_inventory_day(rt["id"], "2026-06-13T00:00:00Z", physical_capacity=10, transient_sold_rooms=9)
        gb = create_group_block(
            rt["id"], "2026-06-13T00:00:00Z", group_name="Echo",
            nights=1, rooms_per_night=2, offered_rate=400,
        )
        evaluate_group_block(gb["id"], "LRV")
        # ceiling 11, available 11-9=2, request 2 -> exactly fills (<= ceiling) -> succeeds
        committed = commit_group_block(gb["id"], rt["version"])
        assert committed["status"] == "COMMITTED"
        inv_after = validate_success(api.get_inventory_day(inv["id"], RM))
        assert inv_after["rooms_available"] == 0, f"expected 0 got {inv_after['rooms_available']}"

    def test_commit_exactly_at_ceiling_holds_rooms(self, api):
        """PRD §3.7: "On a successful commit, each overlapping inventory day has its
        `group_held_rooms` increased by the block's `rooms_per_night` and its
        `rooms_sold` and `rooms_available` recomputed (cascade hop 1)."
        PRD §2.7: "the rooms sold for the night equal the confirmed transient rooms
        plus the rooms held by committed groups."

        Design: Difficulty/boundary_precision_check/group_commit_exactly_fills_oversell_ceiling
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="BoundaryB2", total_rooms=10, overbooking_limit_pct=0.10)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=10)
        inv = create_inventory_day(rt["id"], "2026-06-13T00:00:00Z", physical_capacity=10, transient_sold_rooms=9)
        gb = create_group_block(
            rt["id"], "2026-06-13T00:00:00Z", group_name="Echo",
            nights=1, rooms_per_night=2, offered_rate=400,
        )
        evaluate_group_block(gb["id"], "LRV")
        commit_group_block(gb["id"], rt["version"])
        inv_after = validate_success(api.get_inventory_day(inv["id"], RM))
        # rooms_sold 9 transient + 2 held = 11 == ceiling 11
        assert inv_after["group_held_rooms"] == 2, f"expected 2 got {inv_after['group_held_rooms']}"
        assert inv_after["rooms_sold"] == 11, f"expected 11 got {inv_after['rooms_sold']}"

    def test_aggregate_overlap_second_commit_exceeds_ceiling(self, api):
        """PRD §2.7: "No operation may push the rooms sold for any affected night
        above that night's oversell ceiling; an operation that would breach the
        ceiling on any night it touches is rejected with
        `ERR_OVERSELL_LIMIT_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/group_block_aggregate_capacity_overlap_on_shared_night
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="OverlapA", total_rooms=10)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=10)
        create_inventory_day(rt["id"], "2026-06-17T00:00:00Z", physical_capacity=10, transient_sold_rooms=2)
        gb1 = create_group_block(
            rt["id"], "2026-06-17T00:00:00Z", group_name="Golf",
            nights=1, rooms_per_night=5, offered_rate=400,
        )
        evaluate_group_block(gb1["id"], "LRV")
        commit_group_block(gb1["id"], rt["version"])
        rt_v1 = validate_success(api.get_room_type(rt["id"], RM))["version"]
        gb2 = create_group_block(
            rt["id"], "2026-06-17T00:00:00Z", group_name="Hotel",
            nights=1, rooms_per_night=5, offered_rate=400,
        )
        evaluate_group_block(gb2["id"], "LRV")
        # ceiling 10; 2 transient + 5 held + 5 requested = 12 > 10 -> rejected
        resp = api.commit_group_block(gb2["id"], {"expected_room_type_version": rt_v1}, GSM)
        validate_error(resp, ApiErrorId.ERR_OVERSELL_LIMIT_EXCEEDED.value)

    def test_aggregate_overlap_rejected_commit_leaves_block_uncommitted(self, api):
        """PRD §2.7: "an operation that would breach the ceiling on any night it
        touches is rejected with `ERR_OVERSELL_LIMIT_EXCEEDED`."
        PRD §3.7: "On a successful commit, each overlapping inventory day has its
        `group_held_rooms` increased by the block's `rooms_per_night`."

        Design: Difficulty/resource_temporal_overlap/group_block_aggregate_capacity_overlap_on_shared_night
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="OverlapA2", total_rooms=10)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=10)
        inv = create_inventory_day(rt["id"], "2026-06-17T00:00:00Z", physical_capacity=10, transient_sold_rooms=2)
        gb1 = create_group_block(rt["id"], "2026-06-17T00:00:00Z", group_name="Golf", nights=1, rooms_per_night=5, offered_rate=400)
        evaluate_group_block(gb1["id"], "LRV")
        commit_group_block(gb1["id"], rt["version"])
        rt_v1 = validate_success(api.get_room_type(rt["id"], RM))["version"]
        gb2 = create_group_block(rt["id"], "2026-06-17T00:00:00Z", group_name="Hotel", nights=1, rooms_per_night=5, offered_rate=400)
        evaluate_group_block(gb2["id"], "LRV")
        api.commit_group_block(gb2["id"], {"expected_room_type_version": rt_v1}, GSM)
        # The rejected second commit must hold no rooms: only the first block's 5 are held.
        inv_after = validate_success(api.get_inventory_day(inv["id"], RM))
        assert inv_after["group_held_rooms"] == 5, f"expected only the first block's 5 held, got {inv_after['group_held_rooms']}"
        gb2_after = validate_success(api.get_group_block(gb2["id"], GSM))
        assert gb2_after["status"] == "NEGOTIATING", f"rejected commit must not transition, got {gb2_after['status']}"

    def test_transient_patch_overlapping_committed_group_exceeds_ceiling(self, api):
        """PRD §3.1: "Such an update may not push the night's rooms sold above its
        oversell ceiling, and a violating update is rejected with
        `ERR_OVERSELL_LIMIT_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/transient_update_overlap_with_committed_group_same_night
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="OverlapB", total_rooms=10)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=10)
        inv = create_inventory_day(rt["id"], "2026-06-18T00:00:00Z", physical_capacity=10, transient_sold_rooms=1)
        gb = create_group_block(
            rt["id"], "2026-06-18T00:00:00Z", group_name="India",
            nights=1, rooms_per_night=6, offered_rate=400,
        )
        evaluate_group_block(gb["id"], "LRV")
        commit_group_block(gb["id"], rt["version"])
        # 5 transient + 6 group held = 11 > ceiling 10 -> rejected
        resp = api.update_inventory_day(inv["id"], {"transient_sold_rooms": 5}, RM)
        validate_error(resp, ApiErrorId.ERR_OVERSELL_LIMIT_EXCEEDED.value)

    def test_rejected_transient_patch_leaves_inventory_unchanged(self, api):
        """PRD §3.1: "Such an update may not push the night's rooms sold above its
        oversell ceiling, and a violating update is rejected with
        `ERR_OVERSELL_LIMIT_EXCEEDED`."
        PRD §2.7: "the rooms sold for the night equal the confirmed transient rooms
        plus the rooms held by committed groups."

        Design: Difficulty/resource_temporal_overlap/transient_update_overlap_with_committed_group_same_night
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="OverlapB2", total_rooms=10)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=10)
        inv = create_inventory_day(rt["id"], "2026-06-18T00:00:00Z", physical_capacity=10, transient_sold_rooms=1)
        gb = create_group_block(rt["id"], "2026-06-18T00:00:00Z", group_name="India", nights=1, rooms_per_night=6, offered_rate=400)
        evaluate_group_block(gb["id"], "LRV")
        commit_group_block(gb["id"], rt["version"])
        api.update_inventory_day(inv["id"], {"transient_sold_rooms": 5}, RM)  # rejected
        inv_after = validate_success(api.get_inventory_day(inv["id"], RM))
        # rejected update must not change the night: transient stays 1, group held stays 6
        assert inv_after["transient_sold_rooms"] == 1, f"expected 1 got {inv_after['transient_sold_rooms']}"
        assert inv_after["group_held_rooms"] == 6, f"expected 6 got {inv_after['group_held_rooms']}"


class TestCommitCascade:
    def test_commit_holds_rooms_recomputes_availability_and_kpis(self, api):
        """PRD §3.7: "On a successful commit, each overlapping inventory day has its
        `group_held_rooms` increased by the block's `rooms_per_night` and its
        `rooms_sold` and `rooms_available` recomputed (cascade hop 1), the room
        type's `version` increments by 1, and the property KPIs are recomputed
        (cascade hop 2)."
        PRD §3.8: "`occupancy_pct` is the total rooms sold divided by the total
        available rooms, rounded half-up to 4 decimal places; `adr` is the total
        room revenue divided by the total rooms sold, rounded half-up to 2 decimal
        places; and `revpar` is the total room revenue divided by the total
        available rooms, rounded half-up to 2 decimal places."

        Design: Difficulty/transitive_cascade/commit_holds_rooms_recompute_availability_then_kpi_depth3
        """
        set_clock("2026-06-06T00:00:00Z")
        prop = create_property(name="Cascade3", total_rooms=30)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=30)
        inv = create_inventory_day(rt["id"], "2026-06-06T00:00:00Z", physical_capacity=30,
                                   transient_sold_rooms=8, transient_revenue=2400)
        gb = create_group_block(
            rt["id"], "2026-06-06T00:00:00Z", group_name="Bravo",
            nights=1, rooms_per_night=5, offered_rate=300,
        )
        evaluate_group_block(gb["id"], "LRV")
        commit_group_block(gb["id"], rt["version"])

        inv_after = validate_success(api.get_inventory_day(inv["id"], RM))
        assert inv_after["group_held_rooms"] == 5
        assert inv_after["rooms_sold"] == 13
        assert inv_after["rooms_available"] == 17

        kpis = validate_success(api.get_property_kpis(prop["id"], RM))
        # available 30, sold 13, revenue 2400 + 5*300=1500 -> 3900
        assert kpis["occupancy_pct"] == 0.4333, f"expected 0.4333 got {kpis['occupancy_pct']}"
        assert kpis["adr"] == 300.00, f"expected 300.00 got {kpis['adr']}"
        assert kpis["revpar"] == 130.00, f"expected 130.00 got {kpis['revpar']}"

    def test_commit_cascade_hop1_recomputes_inventory_availability(self, api):
        """PRD §3.7: "On a successful commit, each overlapping inventory day has its
        `group_held_rooms` increased by the block's `rooms_per_night` and its
        `rooms_sold` and `rooms_available` recomputed (cascade hop 1)."
        PRD §2.7: "the rooms still available equal the oversell ceiling minus the
        rooms sold, but never less than zero."

        Design: Difficulty/transitive_cascade/commit_holds_rooms_recompute_availability_then_kpi_depth3
        """
        set_clock("2026-06-06T00:00:00Z")
        prop = create_property(name="Cascade3b", total_rooms=30)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=30)
        inv = create_inventory_day(rt["id"], "2026-06-06T00:00:00Z", physical_capacity=30,
                                   transient_sold_rooms=8, transient_revenue=2400)
        gb = create_group_block(rt["id"], "2026-06-06T00:00:00Z", group_name="Bravo", nights=1, rooms_per_night=5, offered_rate=300)
        evaluate_group_block(gb["id"], "LRV")
        commit_group_block(gb["id"], rt["version"])
        inv_after = validate_success(api.get_inventory_day(inv["id"], RM))
        # ceiling floor(30*1.0)=30; rooms_sold 8+5=13; available 30-13=17 (hop 1 recompute)
        assert inv_after["group_held_rooms"] == 5, f"expected 5 got {inv_after['group_held_rooms']}"
        assert inv_after["rooms_sold"] == 13, f"expected 13 got {inv_after['rooms_sold']}"
        assert inv_after["rooms_available"] == 17, f"expected 17 got {inv_after['rooms_available']}"

    def test_kpis_computed_read_reflects_transient_inventory(self, api):
        """PRD §3.8: "The computation spans all inventory days across the
        property's room types whose `stay_date` equals the current logical date.
        The total available rooms are the sum of those nights' `physical_capacity`;
        the total rooms sold are the sum of those nights' `rooms_sold` (transient
        plus group-held); and the total room revenue is the sum of those nights'
        `transient_revenue` plus, for each committed group block covering the
        current date, that block's held rooms for the night times its
        `offered_rate`."

        Design: Corner/endpoints/kpis_computed_read_reflects_current_state
        """
        set_clock("2026-06-06T00:00:00Z")
        prop = create_property(name="KpiRead", total_rooms=30)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=30)
        create_inventory_day(rt["id"], "2026-06-06T00:00:00Z", physical_capacity=30,
                             transient_sold_rooms=8, transient_revenue=2400)
        kpis = validate_success(api.get_property_kpis(prop["id"], ANALYST))
        # available 30, sold 8, revenue 2400
        assert kpis["occupancy_pct"] == 0.2667, f"expected 0.2667 got {kpis['occupancy_pct']}"
        assert kpis["adr"] == 300.00, f"expected 300.00 got {kpis['adr']}"
        assert kpis["revpar"] == 80.00, f"expected 80.00 got {kpis['revpar']}"


class TestCompensatingInventory:
    def test_commit_then_cancel_restores_inventory(self, api):
        """PRD §3.7: "A `COMMITTED` block goes `COMMITTED → CANCELLED`: each
        overlapping inventory day has its `group_held_rooms` decreased by the
        block's `rooms_per_night` — restoring exactly the rooms it held — with
        availability recomputed, and the property KPIs are recomputed."

        Design: Difficulty/compensating_invariant/group_commit_then_cancel_restores_room_inventory
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="InvariantA", total_rooms=20)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=20)
        inv = create_inventory_day(rt["id"], "2026-06-19T00:00:00Z", physical_capacity=20, transient_sold_rooms=5)
        gb = create_group_block(
            rt["id"], "2026-06-19T00:00:00Z", group_name="Juliet",
            nights=1, rooms_per_night=4, offered_rate=400,
        )
        evaluate_group_block(gb["id"], "LRV")
        commit_group_block(gb["id"], rt["version"])

        cancelled = validate_success(api.cancel_group_block(gb["id"], GSM))
        assert cancelled["status"] == "CANCELLED"
        inv_after = validate_success(api.get_inventory_day(inv["id"], RM))
        assert inv_after["group_held_rooms"] == 0, f"expected 0 got {inv_after['group_held_rooms']}"
        # ceiling floor(20*1.0)=20; 20 - 5 transient = 15
        assert inv_after["rooms_available"] == 15, f"expected 15 got {inv_after['rooms_available']}"

    def test_commit_then_cancel_restores_rooms_sold(self, api):
        """PRD §3.7: "A `COMMITTED` block goes `COMMITTED → CANCELLED`: each
        overlapping inventory day has its `group_held_rooms` decreased by the
        block's `rooms_per_night` — restoring exactly the rooms it held — with
        availability recomputed, and the property KPIs are recomputed."
        PRD §2.7: "the rooms sold for the night equal the confirmed transient rooms
        plus the rooms held by committed groups."

        Design: Difficulty/compensating_invariant/group_commit_then_cancel_restores_room_inventory
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="InvariantA2", total_rooms=20)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=20)
        inv = create_inventory_day(rt["id"], "2026-06-19T00:00:00Z", physical_capacity=20, transient_sold_rooms=5)
        before = validate_success(api.get_inventory_day(inv["id"], RM))
        assert before["rooms_sold"] == 5  # transient only, no group held yet
        gb = create_group_block(rt["id"], "2026-06-19T00:00:00Z", group_name="Juliet", nights=1, rooms_per_night=4, offered_rate=400)
        evaluate_group_block(gb["id"], "LRV")
        commit_group_block(gb["id"], rt["version"])
        validate_success(api.cancel_group_block(gb["id"], GSM))
        after = validate_success(api.get_inventory_day(inv["id"], RM))
        # commit (+4) then cancel (-4) nets to zero: rooms_sold back to the pre-commit 5
        assert after["rooms_sold"] == 5, f"expected rooms_sold restored to 5, got {after['rooms_sold']}"


class TestTransientReservationCycle:
    def test_confirm_consumes_then_cancel_restores(self, api):
        """PRD §3.9: "On confirm, the reservation captures its `booked_rate` from
        the plan's current published rate; each overlapping inventory day has its
        `transient_sold_rooms` increased by the reservation's `rooms` and its
        `transient_revenue` increased by `rooms` times the captured `booked_rate`,
        with availability recomputed; and the property KPIs are recomputed."
        PRD §3.9: "If the reservation was `CONFIRMED`, each overlapping inventory
        day has its `transient_sold_rooms` decreased by the reservation's `rooms`
        and its `transient_revenue` decreased by `rooms` times the captured
        `booked_rate` — restoring exactly the counts it consumed."

        Design: Corner/state_machines/transient_reservation_confirm_then_cancel_releases_inventory
        """
        set_clock("2026-06-06T00:00:00Z")
        prop = create_property(name="ResCycle", total_rooms=30)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=30)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=200, floor_rate=100, ceiling_rate=400,
        )
        inv = create_inventory_day(rt["id"], "2026-06-06T00:00:00Z", physical_capacity=30,
                                   transient_sold_rooms=5, transient_revenue=1000)
        dec = create_rate_decision(plan["id"], "2026-06-06T00:00:00Z", requested_rate=200)
        publish_decision(dec["id"], plan["version"])
        res = create_transient_reservation(rt["id"], plan["id"], "2026-06-06T00:00:00Z", nights=1, rooms=4)
        confirmed = confirm_reservation(res["id"])
        assert confirmed["status"] == "CONFIRMED" and confirmed["booked_rate"] == 200.00

        inv_confirm = validate_success(api.get_inventory_day(inv["id"], RM))
        assert inv_confirm["transient_sold_rooms"] == 9, f"expected 9 got {inv_confirm['transient_sold_rooms']}"

        cancelled = validate_success(api.cancel_transient_reservation(res["id"], RM))
        assert cancelled["status"] == "CANCELLED"
        inv_cancel = validate_success(api.get_inventory_day(inv["id"], RM))
        assert inv_cancel["transient_sold_rooms"] == 5, f"expected 5 (restored) got {inv_cancel['transient_sold_rooms']}"

    def test_check_out_from_held_rejected(self, api):
        """PRD §3.9: "Checking out a `CONFIRMED` reservation (`CONFIRMED →
        CHECKED_OUT`) realizes the stay and is allowed only from `CONFIRMED`
        (otherwise `ERR_INVALID_STATE`)."

        Design: Corner/state_machines/check_out_from_held_returns_invalid_state
        """
        set_clock("2026-06-01T00:00:00Z")
        prop = create_property(name="BadCheckout", total_rooms=30)
        rt = create_room_type(prop["id"], code="KING", name="King", physical_rooms=30)
        plan = create_rate_plan(
            rt["id"], rate_class="BAR", is_master_bar=True,
            base_rate=200, floor_rate=100, ceiling_rate=400,
        )
        create_inventory_day(rt["id"], "2026-06-06T00:00:00Z", physical_capacity=30, transient_sold_rooms=2)
        res = create_transient_reservation(rt["id"], plan["id"], "2026-06-06T00:00:00Z", nights=1, rooms=1)
        resp = api.check_out_transient_reservation(res["id"], RM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
