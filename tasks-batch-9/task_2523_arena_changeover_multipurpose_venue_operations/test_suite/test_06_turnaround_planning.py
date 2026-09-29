"""Opening a turnaround: the derived window, the overnight determination, the
four-component plan with its two ceilings, and the floor-occupancy conflict."""
from test_helpers import (
    ApiErrorId,
    draft_booking,
    open_changeover_order,
    place_hold,
    read_order,
    setup_arena,
    validate_error,
    validate_paginated,
    venue_version,
    TEST_USERS,
)

SUPERVISOR = TEST_USERS["changeover_supervisor_headers"]


def _two_disjoint_ice_to_concert_pairs():
    """An arena whose crew cap is high enough to order a wildly oversized crew,
    carrying two identical outgoing/incoming pairs two days apart."""
    arena = setup_arena(profiles=("ICE", "CONCERT"), crew_headcount_cap=200)
    venue_id = arena["venue_id"]
    for label, day in (("first", "2026-09-10"), ("second", "2026-09-12")):
        ice = draft_booking(
            venue_id, arena["profiles"]["ICE"]["id"], f"Hockey {day}",
            f"{day}T00:00:00Z", f"{day}T03:00:00Z",
            expected_attendance=15_000, rigging_load_kg=3_000,
            promoter_name="Lakeside Hockey Club",
        )
        arena[f"{label}_ice"] = place_hold(ice["id"])
        concert = draft_booking(
            venue_id, arena["profiles"]["CONCERT"]["id"], f"Concert {day}",
            f"{day}T16:00:00Z", f"{day}T19:00:00Z",
            expected_attendance=8_000, rigging_load_kg=5_000,
            promoter_name="Northline Live",
        )
        arena[f"{label}_concert"] = place_hold(concert["id"])
    return arena


def _four_house_configurations_and_two_candidate_windows():
    """One occupied turnaround window, plus two candidate outgoing shows whose
    derived starts land one minute apart on that window's closing edge."""
    arena = setup_arena(profiles=("ICE", "CONCERT", "COURT", "FAMILY"))
    venue_id = arena["venue_id"]
    ice = draft_booking(
        venue_id, arena["profiles"]["ICE"]["id"], "Hockey Sep 9",
        "2026-09-09T00:00:00Z", "2026-09-09T03:00:00Z",
        expected_attendance=15_000, rigging_load_kg=3_000,
        promoter_name="Lakeside Hockey Club",
    )
    arena["ice"] = place_hold(ice["id"])
    concert = draft_booking(
        venue_id, arena["profiles"]["CONCERT"]["id"], "Concert Sep 9",
        "2026-09-09T16:00:00Z", "2026-09-09T19:00:00Z",
        expected_attendance=8_000, rigging_load_kg=5_000,
        promoter_name="Northline Live",
    )
    arena["concert"] = place_hold(concert["id"])
    arena["occupying_order"] = open_changeover_order(
        venue_id, arena["ice"]["id"], arena["concert"]["id"], crew_headcount=40
    )
    early_court = draft_booking(
        venue_id, arena["profiles"]["COURT"]["id"], "Basketball early finish",
        "2026-09-09T12:00:00Z", "2026-09-09T15:14:00Z",
        expected_attendance=12_000, rigging_load_kg=1_000,
        promoter_name="Riverton Athletics",
    )
    arena["early_court"] = place_hold(early_court["id"])
    late_court = draft_booking(
        venue_id, arena["profiles"]["COURT"]["id"], "Basketball late finish",
        "2026-09-09T12:00:00Z", "2026-09-09T15:15:00Z",
        expected_attendance=12_000, rigging_load_kg=1_000,
        promoter_name="Riverton Athletics",
    )
    arena["late_court"] = place_hold(late_court["id"])
    family = draft_booking(
        venue_id, arena["profiles"]["FAMILY"]["id"], "Family show Sep 10",
        "2026-09-10T00:00:00Z", "2026-09-10T03:00:00Z",
        expected_attendance=10_000, rigging_load_kg=1_000,
        promoter_name="Bright Lights Touring",
    )
    arena["family"] = place_hold(family["id"])
    return arena


class TestPlanAssemblyAcrossEveryComponent:
    def test_a_crew_slightly_over_establishment_divides_then_scales_in_two_ceilings(
        self, api
    ):
        """PRD §3.7: "`window_start_utc` is the outgoing event's `event_end_utc` advanced by
        the arena's `min_turnaround_buffer_minutes`, the mandatory idle period the building
        insists on before crews go onto the floor."
        PRD §3.7: "The determination converts the UTC instant to arena-local time by
        subtracting four hours, takes the truncated whole hour of that local time, and reports
        true when that hour is greater than or equal to the arena's
        `overnight_shift_start_local_hour` **or** strictly less than 6."
        PRD §3.7: "The raw minute figure is divided by the factor and the quotient is rounded
        **up** to a whole minute; this is the first ceiling. When and only when
        `overnight_shift` is true, that already-ceiled figure is then multiplied by 1.15 to
        reflect the overnight slowdown and the product is rounded **up** to a whole minute
        again; this is the second ceiling."
        PRD §3.7: "The two ceilings are applied in exactly that order — divide and ceil, then
        scale and ceil — and never collapsed into a single rounding of the raw figure divided
        by the factor and multiplied by the slowdown."

        Design: Difficulty/combinatorial_formula/planned_turnaround_combines_ice_branch_seating_mode_panel_sets_crew_clamp_and_pinned_double_ceiling
        """
        arena = _two_disjoint_ice_to_concert_pairs()
        order = open_changeover_order(
            arena["venue_id"],
            arena["first_ice"]["id"],
            arena["first_concert"]["id"],
            crew_headcount=44,
        )

        assert order["window_start_utc"] == "2026-09-10T03:45:00.000Z"
        assert order["window_end_utc"] == "2026-09-10T16:00:00.000Z"
        assert order["window_minutes"] == 735
        assert order["overnight_shift"] is True, (
            "03:45 UTC is 23:45 arena-local, at or past the overnight start hour"
        )
        assert order["planned_turnaround_minutes"] == 644, (
            "a raw 615 minutes over a factor of 1.1 ceils to 560, then 1.15 ceils to 644"
        )
        assert order["planned_turnaround_minutes"] != 643, (
            "643 collapses the two ceilings into a single rounding"
        )
        assert order["status"] == "PLANNED"

    def test_an_oversized_crew_is_clamped_at_double_productivity(self, api):
        """PRD §3.7: "The **crew-productivity factor** is the order's `crew_headcount` divided
        by the incoming configuration's `crew_size_required`, then clamped to lie between 0.5
        and 2.0: a factor computed below 0.5 is raised to 0.5, and one computed above 2.0 is
        lowered to 2.0."
        PRD §3.7: "An **ice adder** accounts for what has to happen to the deck, and it has
        three branches."
        PRD §3.7: "A **seating adder** accounts for the bowl, read from the incoming
        configuration's `seating_mode`: zero minutes for `FULL_BOWL`, 120 minutes for
        `RETRACTABLE_IN`, and 180 minutes for `CURTAINED_HALF`."
        PRD §3.7: "A **panel adder** accounts for floor protection: the incoming
        configuration's `floor_protection_panels_required` is divided by 40, the number of
        panels in one handling set, and rounded **up** to a whole number of sets, then
        multiplied by 15 minutes per set."

        Design: Difficulty/combinatorial_formula/planned_turnaround_combines_ice_branch_seating_mode_panel_sets_crew_clamp_and_pinned_double_ceiling
        """
        arena = _two_disjoint_ice_to_concert_pairs()
        modest = open_changeover_order(
            arena["venue_id"],
            arena["first_ice"]["id"],
            arena["first_concert"]["id"],
            crew_headcount=44,
        )
        oversized = open_changeover_order(
            arena["venue_id"],
            arena["second_ice"]["id"],
            arena["second_concert"]["id"],
            crew_headcount=200,
        )

        assert oversized["window_minutes"] == 735
        assert oversized["overnight_shift"] is True
        assert oversized["crew_headcount"] == 200
        assert oversized["planned_turnaround_minutes"] == 355, (
            "a factor of five is lowered to two, so 615 halves to 308 then scales to 355"
        )
        assert oversized["planned_turnaround_minutes"] != 354, (
            "354 collapses the two ceilings into one"
        )
        assert oversized["planned_turnaround_minutes"] != 142, (
            "142 would divide by an unclamped factor of five"
        )
        assert oversized["planned_turnaround_minutes"] < modest[
            "planned_turnaround_minutes"
        ]


class TestChangeoverWindowOccupancy:
    def test_a_derived_start_one_minute_inside_the_incumbent_window_is_refused(self, api):
        """PRD §2.7: "**Unbuffered half-open overlap.** Two intervals collide when the first
        starts strictly before the second ends *and* the second starts strictly before the
        first ends."
        PRD §3.7: "Then the arena floor must be free: no other changeover order on the same
        arena whose `status` is neither `SIGNED_OFF` nor `ABANDONED` may overlap this order's
        window under the unbuffered half-open convention of §2.7, otherwise
        `ERR_CHANGEOVER_WINDOW_CONFLICT`."
        PRD §3.7: "`window_start_utc` is the outgoing event's `event_end_utc` advanced by the
        arena's `min_turnaround_buffer_minutes`, the mandatory idle period the building insists
        on before crews go onto the floor."

        Design: Difficulty/resource_temporal_overlap/changeover_windows_reject_a_one_minute_overlap_and_accept_windows_that_merely_touch
        """
        arena = _four_house_configurations_and_two_candidate_windows()
        assert arena["occupying_order"]["window_start_utc"] == (
            "2026-09-09T03:45:00.000Z"
        )
        assert arena["occupying_order"]["window_end_utc"] == "2026-09-09T16:00:00.000Z"
        assert arena["occupying_order"]["planned_turnaround_minutes"] == 708

        response = api.create_changeover_order(
            {
                "from_booking_id": arena["early_court"]["id"],
                "to_booking_id": arena["family"]["id"],
                "crew_headcount": 25,
                "expected_venue_version": venue_version(arena["venue_id"]),
            },
            SUPERVISOR,
        )
        validate_error(response, ApiErrorId.ERR_CHANGEOVER_WINDOW_CONFLICT.value, 409)

        _rows, meta = validate_paginated(
            api.list_changeover_orders(SUPERVISOR, {"venue_id": arena["venue_id"]})
        )
        assert meta["total_count"] == 1, "only the incumbent turnaround exists"

    def test_a_window_that_merely_touches_the_incumbent_is_accepted(self, api):
        """PRD §2.7: "Intervals that merely touch at an endpoint — one ending at exactly the
        instant the next begins — do not collide."
        PRD §3.7: "`window_end_utc` is the incoming event's `event_start_utc` exactly.
        `window_minutes` is the whole number of minutes between those two instants."
        PRD §3.7: "The determination converts the UTC instant to arena-local time by
        subtracting four hours, takes the truncated whole hour of that local time, and reports
        true when that hour is greater than or equal to the arena's
        `overnight_shift_start_local_hour` **or** strictly less than 6."
        PRD §3.7: "A newly opened order has `status` reading `PLANNED`, all three of
        `floor_stage`, `seating_stage` and `infra_stage` sitting at `NOT_STARTED`,
        `actual_turnaround_minutes` unset, `overrun_minutes` at 0, `rework_count` at 0,
        `started_at_utc` and `completed_at_utc` unset, `signed_off_by_user_id` unset,
        `abandon_reason` unset, and `opened_by_user_id` recorded as the supervisor's
        `X-User-ID` — the value that segregation of duties will later compare against at
        sign-off."

        Design: Difficulty/resource_temporal_overlap/changeover_windows_reject_a_one_minute_overlap_and_accept_windows_that_merely_touch
        """
        arena = _four_house_configurations_and_two_candidate_windows()
        response = api.create_changeover_order(
            {
                "from_booking_id": arena["early_court"]["id"],
                "to_booking_id": arena["family"]["id"],
                "crew_headcount": 25,
                "expected_venue_version": venue_version(arena["venue_id"]),
            },
            SUPERVISOR,
        )
        validate_error(response, ApiErrorId.ERR_CHANGEOVER_WINDOW_CONFLICT.value, 409)

        accepted = open_changeover_order(
            arena["venue_id"],
            arena["late_court"]["id"],
            arena["family"]["id"],
            crew_headcount=25,
        )

        assert accepted["window_start_utc"] == "2026-09-09T16:00:00.000Z"
        assert accepted["window_end_utc"] == "2026-09-10T00:00:00.000Z"
        assert accepted["window_minutes"] == 480
        assert accepted["overnight_shift"] is False, (
            "16:00 UTC is 12:00 arena-local, neither late nor early enough"
        )
        assert accepted["planned_turnaround_minutes"] == 215, (
            "a full-bowl family show over a basketball floor needs no ice work and one "
            "panel set, at exactly establishment crew"
        )
        assert accepted["status"] == "PLANNED"

        assert read_order(arena["occupying_order"]["id"])[
            "planned_turnaround_minutes"
        ] == 708
        _rows, meta = validate_paginated(
            api.list_changeover_orders(SUPERVISOR, {"venue_id": arena["venue_id"]})
        )
        assert meta["total_count"] == 2
