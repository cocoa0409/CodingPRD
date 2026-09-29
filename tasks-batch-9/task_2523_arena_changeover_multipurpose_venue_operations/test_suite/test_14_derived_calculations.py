"""Arithmetic that the arena's own configuration drives: the overnight predicate,
the per-tier hold windows, the notice bands, the grid aggregate, the condensation
blend and the readiness projection."""
import pytest

from test_helpers import (
    CLOCK_STARTUP_UTC,
    confirm_booking,
    create_labor_call,
    declare_profile,
    draft_booking,
    install_ice_sheet,
    make_anchor_tenant_rep_headers,
    place_hold,
    read_booking,
    read_labor_call,
    read_venue,
    register_tenant,
    register_venue,
    set_clock,
    setup_arena,
    setup_ice_to_concert_turnaround,
    validate_success,
    venue_version,
    TEST_USERS,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["booking_manager_headers"]
COORDINATOR = TEST_USERS["labor_coordinator_headers"]

RIVERTON = {
    "name": "Riverton Coliseum",
    "rigging_capacity_kg": 15_000,
    "dock_count": 3,
    "max_bowl_seats": 14_000,
    "crew_headcount_cap": 50,
}


def _arena_with_a_held_show():
    """One arena at the default overnight hour with a single held ice show."""
    arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
    draft = draft_booking(
        arena["venue_id"], arena["profiles"]["ICE"]["id"], "Hockey Sep 10",
        "2026-09-10T00:00:00Z", "2026-09-10T03:00:00Z",
        expected_attendance=15_000, rigging_load_kg=3_000,
        promoter_name="Lakeside Hockey Club",
    )
    arena["booking"] = place_hold(draft["id"])
    return arena


class TestTheOvernightPredicateAtBothLocalEdges:
    def test_local_twenty_two_and_local_five_are_overnight_while_twenty_one_and_six_are_not(
        self, api
    ):
        """PRD §3.7: "The determination converts the UTC instant to arena-local time by
        subtracting four hours, takes the truncated whole hour of that local time, and reports
        true when that hour is greater than or equal to the arena's
        `overnight_shift_start_local_hour` **or** strictly less than 6."
        PRD §3.7: "The identical rule is applied to labor calls in §3.9, where it reads the call's
        own start instant instead."
        PRD §3.9: "Its `overnight` flag is computed at creation by the same arena-local rule §3.7
        applies to turnaround windows, evaluated here on `call_start_utc`."
        PRD §3.9: "The overnight multiplier is 1.35 when the call's `overnight` flag is true and
        1.0 otherwise."
        PRD §3.1: "`overnight_shift_start_local_hour` is the arena-local hour from which a shift
        counts as overnight; it accepts 18 through 23 and defaults to 22."

        Design: Corner/calculations/overnight_shift_flag_flips_at_the_local_hour_boundaries_of_22_and_6
        """
        arena = _arena_with_a_held_show()
        assert read_venue(arena["venue_id"])["overnight_shift_start_local_hour"] == 22
        booking_id = arena["booking"]["id"]

        at_local_2200 = create_labor_call(
            "STAGEHAND", 10, "2026-09-10T02:00:00Z", "2026-09-10T10:00:00Z",
            booking_id=booking_id,
        )
        at_local_2100 = create_labor_call(
            "STAGEHAND", 10, "2026-09-10T01:00:00Z", "2026-09-10T09:00:00Z",
            booking_id=booking_id,
        )
        at_local_0500 = create_labor_call(
            "STAGEHAND", 10, "2026-09-10T09:00:00Z", "2026-09-10T17:00:00Z",
            booking_id=booking_id,
        )
        at_local_0600 = create_labor_call(
            "STAGEHAND", 10, "2026-09-10T10:00:00Z", "2026-09-10T18:00:00Z",
            booking_id=booking_id,
        )

        assert at_local_2200["overnight"] is True
        assert at_local_2200["estimated_cost_cents"] == 518_400, (
            "51840 cents a head at the overnight multiplier, times ten heads"
        )
        assert at_local_2100["overnight"] is False
        assert at_local_2100["estimated_cost_cents"] == 384_000
        assert at_local_0500["overnight"] is True, "local hour five is strictly below six"
        assert at_local_0500["estimated_cost_cents"] == 518_400
        assert at_local_0600["overnight"] is False, "local hour six is not below six"
        assert at_local_0600["estimated_cost_cents"] == 384_000

        for call in (at_local_2200, at_local_2100, at_local_0500, at_local_0600):
            assert call["guaranteed_hours"] == 4
            assert call["status"] == "CALLED"


class TestHoldWindowsPinnedByTier:
    def test_four_holds_placed_at_one_instant_expire_on_four_different_days(self, api):
        """PRD §3.2: "A `TIER_1` hold runs for fourteen days from the instant it is placed; a
        `TIER_2` hold runs for seven days; a `TIER_3` hold runs for three days; and a promoter hold
        at `OPEN` runs for twenty-four hours."
        PRD §3.3: "`hold_expires_at` is then computed as `hold_placed_at` advanced by the pinned
        tier's hold window from §3.2 — fourteen days for `TIER_1`, seven days for `TIER_2`, three
        days for `TIER_3`, twenty-four hours for `OPEN` — using whole-hour arithmetic and rendered
        as an ISO 8601 UTC instant with three fractional digits."
        PRD §3.3: "Supplying `tenant_id` makes the booking an anchor booking; omitting it makes it
        a promoter booking, in which case `promoter_name` becomes mandatory and the booking will
        hold at the pseudo-tier `OPEN`."
        PRD §2.11: "`open_hold_count` is the number of bookings on the arena whose `status` is
        either `HELD` or `CHALLENGED`."

        Design: Corner/calculations/hold_window_hours_are_snapshotted_per_tier_at_hold_time
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
        venue_id = arena["venue_id"]
        profile_id = arena["profiles"]["ICE"]["id"]

        tiers = {
            "TIER_1": ("Lakeside Hockey Club", "10", "2026-08-15T00:00:00.000Z"),
            "TIER_2": ("Riverton Athletics", "11", "2026-08-08T00:00:00.000Z"),
            "TIER_3": ("Northline Skating", "12", "2026-08-04T00:00:00.000Z"),
        }
        held = {}
        for tier, (tenant_name, day, _expected) in tiers.items():
            tenant = register_tenant(venue_id, tenant_name, tier, 5)
            draft = draft_booking(
                venue_id, profile_id, f"Anchor show Sep {day}",
                f"2026-09-{day}T00:00:00Z", f"2026-09-{day}T03:00:00Z",
                expected_attendance=15_000, rigging_load_kg=3_000,
                tenant_id=tenant["id"],
            )
            held[tier] = validate_success(
                api.hold_event_booking(
                    draft["id"], make_anchor_tenant_rep_headers(tenant["id"])
                ),
                200,
            )

        promoter_draft = draft_booking(
            venue_id, profile_id, "Promoter show Sep 13",
            "2026-09-13T00:00:00Z", "2026-09-13T03:00:00Z",
            expected_attendance=15_000, rigging_load_kg=3_000,
            promoter_name="Lakeside Hockey Club",
        )
        held["OPEN"] = place_hold(promoter_draft["id"])

        for tier, (_name, _day, expected_expiry) in tiers.items():
            assert held[tier]["hold_tier"] == tier
            assert held[tier]["hold_expires_at"] == expected_expiry
        assert held["OPEN"]["hold_tier"] == "OPEN"
        assert held["OPEN"]["hold_expires_at"] == "2026-08-02T00:00:00.000Z"

        for row in held.values():
            assert row["hold_placed_at"] == "2026-08-01T00:00:00.000Z"

        assert read_venue(venue_id)["open_hold_count"] == 4


class TestCancellationNoticeBands:
    def test_the_free_band_the_quarter_band_and_the_half_band_land_on_their_edges(
        self, api
    ):
        """PRD §3.9: "The notice period is the number of hours from the logical clock instant to
        `call_start_utc`, and it may be negative when the call start has already passed."
        PRD §3.9: "Notice of at least 48 hours attracts no fee at all; otherwise notice of at
        least 12 hours attracts a quarter of the estimate; otherwise half the estimate is
        charged."
        PRD §3.9: "Both comparisons are inclusive, so exactly 48 hours notice is free and exactly
        12 hours notice is the quarter band."
        PRD §3.9: "`cancellation_fee_cents` is that fraction of `estimated_cost_cents` — read as
        stored and never recomputed — rounded half up to whole cents."
        PRD §3.9: "The call moves `CALLED → CANCELLED` and `settled_cost_cents` stays unset,
        because cancelled work is never settled."

        Design: Corner/calculations/labor_cancellation_fee_bands_at_exactly_48_and_12_hours_notice
        """
        arena = _arena_with_a_held_show()
        confirm_booking(arena["booking"]["id"], arena["venue_id"])
        booking_id = arena["booking"]["id"]

        calls = [
            create_labor_call(
                "STAGEHAND", 10, "2026-09-10T02:00:00Z", "2026-09-10T10:00:00Z",
                booking_id=booking_id,
            )
            for _ in range(3)
        ]
        for call in calls:
            assert call["estimated_cost_cents"] == 518_400

        set_clock("2026-09-08T02:00:00Z")
        free = validate_success(
            api.cancel_labor_call(calls[0]["id"], COORDINATOR), 200
        )
        assert free["status"] == "CANCELLED"
        assert free["cancellation_fee_cents"] == 0, "exactly forty-eight hours is free"

        set_clock("2026-09-09T14:00:00Z")
        quarter = validate_success(
            api.cancel_labor_call(calls[1]["id"], COORDINATOR), 200
        )
        assert quarter["cancellation_fee_cents"] == 129_600, (
            "exactly twelve hours notice is the quarter band"
        )

        set_clock("2026-09-09T15:00:00Z")
        half = validate_success(
            api.cancel_labor_call(calls[2]["id"], COORDINATOR), 200
        )
        assert half["cancellation_fee_cents"] == 259_200, (
            "eleven hours notice falls through to half the estimate"
        )

        for call in calls:
            stored = read_labor_call(call["id"])
            assert stored["status"] == "CANCELLED"
            assert stored["settled_cost_cents"] is None
            assert stored["estimated_cost_cents"] == 518_400


class TestTheRoofGridAggregate:
    def test_only_a_confirmed_show_whose_interval_contains_the_clock_is_counted(
        self, api
    ):
        """PRD §3.3: "The stored arena field `rigging_committed_load_kg` uses exactly the same
        closed-interval arithmetic with the logical clock instant standing in as a zero-length
        candidate window: it is the sum of `rigging_load_kg` over confirmed bookings whose closed
        event interval contains the current instant."
        PRD §3.3: "Bookings in `DRAFT`, `HELD`, `CHALLENGED`, `RELEASED` or `DISPLACED` contribute
        nothing to the figure."
        PRD §3.3: "Both figures are carried to two decimal places, rounded half up."
        PRD §2.11: "`rigging_committed_load_kg` is the aggregate suspended load currently hanging,
        defined in §3.3."

        Design: Corner/calculations/rigging_committed_load_counts_only_confirmed_bookings_whose_window_contains_now
        """
        arena = setup_arena(profiles=("ICE",), clock=CLOCK_STARTUP_UTC)
        venue_id = arena["venue_id"]
        profile_id = arena["profiles"]["ICE"]["id"]

        show_a = draft_booking(
            venue_id, profile_id, "Hockey Sep 10",
            "2026-09-10T00:00:00Z", "2026-09-10T03:00:00Z",
            expected_attendance=15_000, rigging_load_kg=3_000,
            promoter_name="Lakeside Hockey Club",
        )
        place_hold(show_a["id"])
        confirm_booking(show_a["id"], venue_id)

        show_c = draft_booking(
            venue_id, profile_id, "Never held rehearsal",
            "2026-09-10T01:00:00Z", "2026-09-10T02:00:00Z",
            expected_attendance=5_000, rigging_load_kg=9_000,
            promoter_name="Lakeside Hockey Club",
        )
        show_b = draft_booking(
            venue_id, profile_id, "Hockey Sep 12",
            "2026-09-12T00:00:00Z", "2026-09-12T03:00:00Z",
            expected_attendance=15_000, rigging_load_kg=5_000,
            promoter_name="Lakeside Hockey Club",
        )

        set_clock("2026-09-10T01:00:00Z")
        place_hold(show_b["id"])
        confirmed_b = validate_success(
            api.confirm_event_booking(
                show_b["id"],
                {"expected_venue_version": venue_version(venue_id)},
                MANAGER,
            ),
            200,
        )
        assert confirmed_b["status"] == "CONFIRMED"

        venue = read_venue(venue_id)
        assert float(venue["rigging_committed_load_kg"]) == pytest.approx(
            3_000.00, abs=0.005
        ), "only the September tenth show is hanging at the clock instant"

        assert read_booking(show_c["id"])["status"] == "DRAFT"
        assert float(read_booking(show_c["id"])["rigging_load_kg"]) == pytest.approx(
            9_000.00, abs=0.005
        ), "the draft's load is stored but excluded from the aggregate"


class TestTheCondensationBlend:
    def test_a_nominal_sheet_scores_zero_while_a_thin_underserved_sheet_scores_the_blend(
        self, api
    ):
        """PRD §3.6: "The **dehumidification deficit** is zero outright when
        `required_dehumidification_lph` is zero; otherwise it is the shortfall of
        `dehumidification_lph_applied` against `required_dehumidification_lph` divided by
        `required_dehumidification_lph`, floored at zero so that over-provisioning does not produce
        a negative contribution."
        PRD §3.6: "The **thickness deficit** is the shortfall of `sheet_thickness_mm` against a
        nominal 32 millimetres divided by that same 32, floored at zero, so a
        thicker-than-nominal sheet contributes nothing."
        PRD §3.6: "Those three are combined with weights of 0.45 for the dehumidification deficit,
        0.30 for the cover load and 0.25 for the thickness deficit; the weighted sum is multiplied
        by 100 and rounded half up to two decimal places to give `condensation_risk_score`."
        PRD §3.6: "The install snapshots the profile's moisture demand onto the sheet as
        `required_dehumidification_lph`."
        PRD §3.6: "And the applied dehumidification must be at least one quarter of the profile's
        `dehumidification_required_lph` — evaluated inclusively, so exactly a quarter of the demand
        passes — otherwise `ERR_DEHUMIDIFICATION_INSUFFICIENT`."

        Design: Corner/calculations/condensation_risk_score_combines_the_dehumidification_and_thickness_deficits
        """
        set_clock(CLOCK_STARTUP_UTC)
        lakeside = register_venue()
        lakeside_ice = declare_profile(lakeside["id"], "ICE")
        riverton = register_venue(**RIVERTON)
        riverton_ice = declare_profile(riverton["id"], "ICE")

        nominal = install_ice_sheet(
            lakeside["id"], lakeside_ice["id"],
            dehumidification_lph_applied=120, sheet_thickness_mm=32,
        )
        deficient = install_ice_sheet(
            riverton["id"], riverton_ice["id"],
            dehumidification_lph_applied=60, sheet_thickness_mm=24,
        )

        assert float(nominal["condensation_risk_score"]) == pytest.approx(
            0.00, abs=0.005
        )
        assert float(nominal["required_dehumidification_lph"]) == pytest.approx(
            120, abs=0.005
        )
        assert float(deficient["condensation_risk_score"]) == pytest.approx(
            28.75, abs=0.005
        ), "half the moisture demand and a quarter thin, weighted and scaled"
        assert deficient["status"] == "BUILDING", (
            "sixty litres per hour clears the quarter-of-demand install floor"
        )

        for sheet in (nominal, deficient):
            assert float(sheet["cover_hours_accumulated"]) == pytest.approx(
                0, abs=0.0005
            )
            assert sheet["cover_cycles"] == 0


class TestTheReadinessProjection:
    def test_a_planned_turnaround_reports_its_slack_and_every_blocker_in_order(
        self, api
    ):
        """PRD §3.8: "It reports the order's identifier as `order_id` alongside its `status`,
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
        anything other than `BROADCAST_READY`; and finally `CHANGEOVER_DEBT_FREEZE` when the
        arena's `changeover_debt_minutes` has reached or passed three hours."
        PRD §3.7: "`window_start_utc` is the outgoing event's `event_end_utc` advanced by the
        arena's `min_turnaround_buffer_minutes`, the mandatory idle period the building insists on
        before crews go onto the floor."
        PRD §3.7: "The raw minute figure is divided by the factor and the quotient is rounded
        **up** to a whole minute; this is the first ceiling."
        PRD §3.7: "When and only when `overnight_shift` is true, that already-ceiled figure is
        then multiplied by 1.15 to reflect the overnight slowdown and the product is rounded **up**
        to a whole minute again; this is the second ceiling."
        PRD §3.7: "A newly opened order has `status` reading `PLANNED`, all three of `floor_stage`,
        `seating_stage` and `infra_stage` sitting at `NOT_STARTED`, `actual_turnaround_minutes`
        unset, `overrun_minutes` at 0, `rework_count` at 0, `started_at_utc` and `completed_at_utc`
        unset, `signed_off_by_user_id` unset, `abandon_reason` unset, and `opened_by_user_id`
        recorded as the supervisor's `X-User-ID` — the value that segregation of duties will later
        compare against at sign-off."

        Design: Corner/calculations/readiness_projection_lists_blocking_reasons_in_the_declared_order
        """
        arena = setup_ice_to_concert_turnaround(crew_headcount=40)
        order = arena["order"]

        readiness = validate_success(
            api.get_changeover_readiness(order["id"], DIRECTOR), 200
        )

        assert readiness["order_id"] == order["id"]
        assert readiness["status"] == "PLANNED"
        assert readiness["window_minutes"] == 735, (
            "three in the morning plus the forty-five minute buffer, out to four in "
            "the afternoon"
        )
        assert readiness["planned_turnaround_minutes"] == 708
        assert readiness["slack_minutes"] == 27
        assert readiness["blocking_reasons"] == [
            "INCOMING_BOOKING_NOT_CONFIRMED",
            "FLOOR_PROTECTION_SHORTFALL",
            "FLOOR_INCOMPLETE",
            "SEATING_INCOMPLETE",
            "INFRA_INCOMPLETE",
        ]
        assert "CHANGEOVER_DEBT_FREEZE" not in readiness["blocking_reasons"], (
            "a fresh arena carries no accumulated overrun"
        )
        assert readiness["floor_stage"] == "NOT_STARTED"
        assert readiness["seating_stage"] == "NOT_STARTED"
        assert readiness["infra_stage"] == "NOT_STARTED"
