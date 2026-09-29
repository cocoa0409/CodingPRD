"""What the HTTP surface itself promises: round-trip reads, filtered listings,
paginated meta, reverse reachability, and reads that never mutate."""
from test_helpers import (
    ApiErrorId,
    CLOCK_STARTUP_UTC,
    create_equipment_pool,
    draft_booking,
    place_hold,
    read_asset,
    read_booking,
    read_order,
    read_venue,
    set_clock,
    setup_arena,
    setup_ice_to_concert_turnaround,
    validate_error,
    validate_paginated,
    validate_success,
    venue_version,
    TEST_USERS,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["booking_manager_headers"]
SUPERVISOR = TEST_USERS["changeover_supervisor_headers"]
COORDINATOR = TEST_USERS["labor_coordinator_headers"]

UNKNOWN_ASSET_ID = "00000000-0000-4000-8000-0000000000aa"
UNKNOWN_ORDER_ID = "00000000-0000-4000-8000-0000000000bb"


class TestEquipmentPoolReadsAndListings:
    def test_two_pools_round_trip_by_id_and_filter_by_class_status_and_page(self, api):
        """PRD §3.9: "A new pool has `units_available` equal to `units_total`,
        `units_out_of_service` at 0, `cycles_since_service` at 0, `service_due` false and `status`
        reading `IN_SERVICE`, the only alternative being `OUT_OF_SERVICE`."
        PRD §3.9: "Pools are readable individually and through an arena-scoped list narrowed by
        `asset_class` and `status`."
        PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`, `total_count` (the
        number of rows matching the filters before pagination is applied) and `has_more` (true when
        rows remain beyond the current page)."
        PRD §3.9: "A `VenueOperationsDirector` creates each pool against an arena with an
        `asset_class` of `STAGE_DECK`, `DASHER_BOARD_SET`, `FLOOR_PANEL_SET`, `CURTAIN_SYSTEM`,
        `ICE_COVER_PANEL_SET` or `BASKETBALL_FLOOR`; a `units_total` between 1 and 500, which is the
        conserved quantity of the whole inventory; and optionally a `service_interval_cycles`
        between 1 and 200, defaulting to twelve, being the number of issue-and-return cycles between
        mandatory servicing."

        Design: Corner/endpoints/equipment_asset_create_read_and_list_round_trip_with_filters
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
        venue_id = arena["venue_id"]
        deck = create_equipment_pool(venue_id, "STAGE_DECK", 6)
        panels = create_equipment_pool(
            venue_id, "FLOOR_PANEL_SET", 8, service_interval_cycles=4
        )
        version_before_reads = venue_version(venue_id)

        row = validate_success(api.get_equipment_asset(panels["id"], SUPERVISOR), 200)
        assert row["id"] == panels["id"]
        assert row["venue_id"] == venue_id
        assert row["asset_class"] == "FLOOR_PANEL_SET"
        assert row["units_total"] == 8
        assert row["units_available"] == 8
        assert row["units_out_of_service"] == 0
        assert row["service_interval_cycles"] == 4
        assert row["cycles_since_service"] == 0
        assert row["service_due"] is False
        assert row["status"] == "IN_SERVICE"

        _all_rows, all_meta = validate_paginated(
            api.list_venue_equipment_assets(venue_id, DIRECTOR)
        )
        assert all_meta["total_count"] == 2
        assert all_meta["has_more"] is False

        deck_rows, deck_meta = validate_paginated(
            api.list_venue_equipment_assets(
                venue_id, DIRECTOR, {"asset_class": "STAGE_DECK"}
            )
        )
        assert deck_meta["total_count"] == 1
        assert [r["id"] for r in deck_rows] == [deck["id"]]

        idle_rows, idle_meta = validate_paginated(
            api.list_venue_equipment_assets(
                venue_id, DIRECTOR, {"status": "OUT_OF_SERVICE"}
            )
        )
        assert idle_meta["total_count"] == 0
        assert idle_rows == []

        page_rows, page_meta = validate_paginated(
            api.list_venue_equipment_assets(
                venue_id, DIRECTOR, {"limit": 1, "offset": 0}
            )
        )
        assert len(page_rows) == 1
        assert page_meta["total_count"] == 2, (
            "the count precedes pagination"
        )
        assert page_meta["has_more"] is True

        assert venue_version(venue_id) == version_before_reads, (
            "four reads leave the arena row alone"
        )

    def test_an_issue_needs_both_rows_and_is_then_reachable_from_either_side(self, api):
        """PRD §2.9: "The unresolved-identifier vocabulary is specific: `ERR_VENUE_NOT_FOUND` for
        an arena, `ERR_PROFILE_NOT_FOUND` for a `config_profile_id`, `ERR_TENANT_NOT_FOUND` for a
        `tenant_id` or a `challenger_tenant_id`, `ERR_BOOKING_NOT_FOUND` for any booking reference
        in a path or body, `ERR_CHALLENGE_NOT_FOUND` for a challenge in a path,
        `ERR_CHANGEOVER_ORDER_NOT_FOUND` for a turnaround in a path or body,
        `ERR_ICE_SHEET_NOT_FOUND` for an ice sheet in a path, `ERR_DOCK_RESERVATION_NOT_FOUND` for a
        dock reservation in a path, `ERR_LABOR_CALL_NOT_FOUND` for a labor call in a path, and
        `ERR_EQUIPMENT_NOT_FOUND` for either an equipment pool or an equipment issue in a path or
        body."
        PRD §2.9: "All ten carry HTTP 404."
        PRD §3.9: "An issue is the many-to-many junction between a pool and a turnaround."
        PRD §3.9: "The issue is created `ISSUED` — the only other state is `RETURNED`, which is
        terminal — and the pool's `units_available` falls by `units_issued`."
        PRD §3.9: "Issues are readable individually and as a list narrowed by `asset_id`,
        `changeover_order_id` and `status`."

        Design: Corner/endpoints/equipment_issue_links_the_asset_and_the_order_and_unknown_ids_return_not_found
        """
        arena = setup_ice_to_concert_turnaround(crew_headcount=40)
        order_id = arena["order"]["id"]
        pool = create_equipment_pool(arena["venue_id"], "STAGE_DECK", 6)

        unknown_asset = api.create_equipment_issue(
            {
                "asset_id": UNKNOWN_ASSET_ID,
                "changeover_order_id": order_id,
                "units_issued": 2,
            },
            SUPERVISOR,
        )
        validate_error(unknown_asset, ApiErrorId.ERR_EQUIPMENT_NOT_FOUND.value, 404)

        unknown_order = api.create_equipment_issue(
            {
                "asset_id": pool["id"],
                "changeover_order_id": UNKNOWN_ORDER_ID,
                "units_issued": 2,
            },
            SUPERVISOR,
        )
        validate_error(
            unknown_order, ApiErrorId.ERR_CHANGEOVER_ORDER_NOT_FOUND.value, 404
        )

        issue = validate_success(
            api.create_equipment_issue(
                {
                    "asset_id": pool["id"],
                    "changeover_order_id": order_id,
                    "units_issued": 2,
                },
                SUPERVISOR,
            ),
            201,
        )
        assert issue["asset_id"] == pool["id"]
        assert issue["changeover_order_id"] == order_id
        assert issue["units_issued"] == 2
        assert issue["damaged_units"] == 0
        assert issue["status"] == "ISSUED"
        assert issue["returned_at_utc"] is None

        by_asset, asset_meta = validate_paginated(
            api.list_equipment_issues(SUPERVISOR, {"asset_id": pool["id"]})
        )
        assert asset_meta["total_count"] == 1
        by_order, order_meta = validate_paginated(
            api.list_equipment_issues(SUPERVISOR, {"changeover_order_id": order_id})
        )
        assert order_meta["total_count"] == 1
        assert by_asset[0]["id"] == by_order[0]["id"] == issue["id"]

        stored_pool = read_asset(pool["id"])
        assert stored_pool["units_available"] == 4
        assert stored_pool["units_total"] == 6


class TestTheReadinessRead:
    def test_the_projection_reports_slack_and_blockers_without_touching_the_order(
        self, api
    ):
        """PRD §3.8: "A read-only readiness projection lets any role see where an order stands."
        PRD §3.8: "It reports the order's identifier as `order_id` alongside its `status`,
        `floor_stage`, `seating_stage`, `infra_stage`, `window_minutes` and
        `planned_turnaround_minutes`, plus `slack_minutes` — the `window_minutes` less the
        `planned_turnaround_minutes`, which may be negative — and `blocking_reasons`, a list of
        strings appended in exactly this fixed order: `INCOMING_BOOKING_NOT_CONFIRMED` when the
        incoming booking's `status` is anything other than `CONFIRMED`; then
        `FLOOR_PROTECTION_SHORTFALL` when `floor_stage` is still `NOT_STARTED` and the issued
        floor-panel-set units on this order fall short of the incoming configuration's panel
        requirement divided by 40 and rounded up; then `FLOOR_INCOMPLETE` when `floor_stage` is
        anything other than `FLOOR_COMPLETE`; then `SEATING_INCOMPLETE` when `seating_stage` is
        anything other than `SEATING_COMPLETE`; then `INFRA_INCOMPLETE` when `infra_stage` is
        anything other than `BROADCAST_READY`; and finally `CHANGEOVER_DEBT_FREEZE` when the arena's
        `changeover_debt_minutes` has reached or passed three hours."
        PRD §3.7: "`window_minutes` is the whole number of minutes between those two instants."
        PRD §3.7: "`planned_turnaround_minutes` is the forward-looking plan, frozen once at creation
        and never recomputed for the life of the order."

        Design: Corner/endpoints/readiness_read_reports_slack_and_the_ordered_blocking_reasons_without_mutating_the_order
        """
        arena = setup_ice_to_concert_turnaround(
            crew_headcount=40, confirm_incoming=True
        )
        order_id = arena["order"]["id"]
        version_before = venue_version(arena["venue_id"])

        readiness = validate_success(
            api.get_changeover_readiness(order_id, COORDINATOR), 200
        )

        assert readiness["order_id"] == order_id
        assert readiness["status"] == "PLANNED"
        assert readiness["window_minutes"] == 735
        assert readiness["planned_turnaround_minutes"] == 708
        assert readiness["slack_minutes"] == 27
        assert readiness["floor_stage"] == "NOT_STARTED"
        assert readiness["seating_stage"] == "NOT_STARTED"
        assert readiness["infra_stage"] == "NOT_STARTED"
        assert readiness["blocking_reasons"] == [
            "FLOOR_PROTECTION_SHORTFALL",
            "FLOOR_INCOMPLETE",
            "SEATING_INCOMPLETE",
            "INFRA_INCOMPLETE",
        ], "the confirmed incoming show drops the first reason from the list"

        order = read_order(order_id)
        assert order["status"] == "PLANNED"
        assert order["started_at_utc"] is None
        assert venue_version(arena["venue_id"]) == version_before, (
            "a projection is a read"
        )


class TestTheHoldExpirySweepOnAnEmptySet:
    def test_a_sweep_a_second_early_is_a_no_op_and_the_same_sweep_at_expiry_harvests(
        self, api
    ):
        """PRD §3.5: "When nothing matches, the sweep is a no-op that reports a `swept_count` of 0
        and an empty `released_booking_ids` list, and the arena's `version` is **not** incremented; a
        sweep that releases at least one booking increments the arena's `version` by exactly one in
        total."
        PRD §3.5: "The sweep gathers every booking on that arena whose `status` is `HELD` or
        `CHALLENGED` and whose `hold_expires_at` is at or before the logical clock instant — a
        booking whose expiry equals the clock instant exactly *is* swept."
        PRD §3.5: "The response reports `swept_count`, the number of bookings released;
        `released_booking_ids`, their identifiers listed in the same pinned processing order; and
        `venue_version`, the arena's `version` after the sweep."
        PRD §3.5: "Each swept booking takes the same release transition it would take individually
        — `HELD → RELEASED` or `CHALLENGED → RELEASED`, including the challenge-denial step for a
        contested booking — except that its `release_reason` is written as the literal string
        `HOLD_EXPIRY_SWEEP` rather than a caller-supplied reason."

        Design: Corner/endpoints/hold_expiry_sweep_that_matches_nothing_returns_zero_and_leaves_the_venue_version_untouched
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
        venue_id = arena["venue_id"]
        draft = draft_booking(
            venue_id, arena["profiles"]["ICE"]["id"], "Promoter game Sep 10",
            "2026-09-10T00:00:00Z", "2026-09-10T03:00:00Z",
            expected_attendance=15_000, rigging_load_kg=3_000,
            promoter_name="Lakeside Hockey Club",
        )
        booking = place_hold(draft["id"])
        assert booking["hold_expires_at"] == "2026-08-02T00:00:00.000Z"
        version_before = venue_version(venue_id)

        empty = validate_success(api.hold_expiry_sweep(venue_id, MANAGER), 200)
        assert empty["swept_count"] == 0
        assert empty["released_booking_ids"] == []
        assert empty["venue_version"] == version_before, (
            "an empty sweep is not a mutation"
        )
        assert read_booking(booking["id"])["status"] == "HELD"
        assert read_venue(venue_id)["open_hold_count"] == 1

        set_clock("2026-08-02T00:00:00Z")
        harvest = validate_success(api.hold_expiry_sweep(venue_id, MANAGER), 200)
        assert harvest["swept_count"] == 1, "an expiry equal to the clock is swept"
        assert harvest["released_booking_ids"] == [booking["id"]]
        assert harvest["venue_version"] == version_before + 1

        swept = read_booking(booking["id"])
        assert swept["status"] == "RELEASED"
        assert swept["release_reason"] == "HOLD_EXPIRY_SWEEP"
        assert read_venue(venue_id)["open_hold_count"] == 0
