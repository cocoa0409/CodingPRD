"""Floor execution on the three parallel work dimensions, rework, and the
director sign-off that measures the turnaround and charges its overrun."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_equipment_pool,
    drive_order_to_ready_for_signoff,
    install_ice_sheet,
    issue_equipment,
    open_changeover_order,
    progress_order,
    read_ice_sheet,
    read_order,
    read_venue,
    rework_order,
    set_clock,
    setup_arena,
    setup_covering_turnaround_ready_for_signoff,
    setup_ice_to_concert_bookings,
    setup_ice_to_concert_turnaround,
    signoff_order,
    transition_ice_sheet,
    validate_error,
    validate_success,
    confirm_booking,
    TEST_USERS,
)

SUPERVISOR = TEST_USERS["changeover_supervisor_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def _confirmed_turnaround_ready_to_work():
    """One open turnaround whose incoming show is CONFIRMED and whose floor
    protection is already on site, with the clock parked at 04:00 on the day."""
    arena = setup_ice_to_concert_turnaround(
        crew_headcount=40, confirm_incoming=True, floor_panel_units_total=10
    )
    arena["floor_issue"] = issue_equipment(
        arena["floor_pool"]["id"], arena["order"]["id"], 3
    )
    set_clock("2026-09-10T04:00:00Z")
    return arena


def _turnaround_with_merely_held_incoming():
    arena = setup_ice_to_concert_turnaround(
        crew_headcount=40, confirm_incoming=False, floor_panel_units_total=10
    )
    arena["floor_issue"] = issue_equipment(
        arena["floor_pool"]["id"], arena["order"]["id"], 3
    )
    return arena


def _thrice_covered_deck_arena():
    """An arena whose sheet has been covered and uncovered three times, leaving
    it IN_SERVICE with six accumulated cover hours."""
    arena = setup_arena(profiles=("ICE", "CONCERT"))
    sheet = install_ice_sheet(
        arena["venue_id"], arena["profiles"]["ICE"]["id"],
        dehumidification_lph_applied=120, sheet_thickness_mm=32,
    )
    sheet = transition_ice_sheet(sheet["id"], "IN_SERVICE")
    for hour in (2, 4, 6):
        transition_ice_sheet(sheet["id"], "COVERED")
        set_clock(f"2026-08-01T{hour:02d}:00:00Z")
        sheet = transition_ice_sheet(sheet["id"], "IN_SERVICE")
    arena["ice_sheet"] = sheet
    return arena


def _covering_turnaround_over_a_thrice_covered_deck():
    arena = _thrice_covered_deck_arena()
    arena["floor_pool"] = create_equipment_pool(
        arena["venue_id"], "FLOOR_PANEL_SET", 10
    )
    setup_ice_to_concert_bookings(arena, confirm_incoming=True)
    arena["order"] = open_changeover_order(
        arena["venue_id"],
        arena["from_booking"]["id"],
        arena["to_booking"]["id"],
        crew_headcount=40,
    )
    issue_equipment(arena["floor_pool"]["id"], arena["order"]["id"], 3)
    arena["order"] = drive_order_to_ready_for_signoff(
        arena["order"]["id"],
        start_clock="2026-09-10T04:00:00Z",
        complete_clock="2026-09-10T16:30:00Z",
    )
    return arena


class TestPlannedVersusActualTurnaround:
    def test_the_frozen_plan_ignores_the_idle_minutes_the_chronological_actual_absorbs(
        self, api
    ):
        """PRD §3.7: "`planned_turnaround_minutes` is the forward-looking plan, frozen once
        at creation and never recomputed for the life of the order."
        PRD §3.7: "It reads no execution history at all and is blind to rework and idle time."
        PRD §3.8: "The chronological measurement is then written: `actual_turnaround_minutes`
        is the span from `started_at_utc` to `completed_at_utc`, expressed in whole minutes
        with any fractional minute discarded — rounded down."
        PRD §3.8: "Because that span reads only the two logical-clock stamps, it necessarily
        includes every minute the order spent in `REWORK` and every idle minute between
        progress calls, which is precisely why it diverges from the frozen
        `planned_turnaround_minutes` even when the configuration inputs are identical."

        Design: Difficulty/dual_variant_calc/turnaround_planned_variant_blind_to_rework_and_idle_minutes_while_actual_absorbs_them
        """
        arena = setup_covering_turnaround_ready_for_signoff()
        order = arena["order"]

        assert order["window_minutes"] == 735
        assert order["overnight_shift"] is True
        assert order["planned_turnaround_minutes"] == 708
        assert order["started_at_utc"] == "2026-09-10T04:00:00.000Z"
        assert order["completed_at_utc"] == "2026-09-10T16:30:00.000Z"

        signed = signoff_order(order["id"], "dir-lakeside")

        assert signed["actual_turnaround_minutes"] == 750, (
            "04:00 to 16:30 is 750 whole minutes of elapsed clock"
        )
        assert signed["planned_turnaround_minutes"] == 708
        assert signed["actual_turnaround_minutes"] != signed[
            "planned_turnaround_minutes"
        ], "the plan is frozen at creation and never absorbs execution history"

    def test_signoff_records_the_director_and_charges_the_overrun_to_the_debt_ledger(
        self, api
    ):
        """PRD §3.8: "On acceptance the order moves `READY_FOR_SIGNOFF → SIGNED_OFF` and
        `signed_off_by_user_id` records the director's `X-User-ID`."
        PRD §3.8: "`overrun_minutes` is then the amount by which the actual measurement
        exceeds `window_minutes`, floored at zero: an order that finished inside its window
        records an overrun of 0."
        PRD §3.8: "The arena's `changeover_debt_minutes` rises by exactly this order's
        `overrun_minutes`."
        PRD §2.11: "`ice_deck_status` mirrors the arena's single ice sheet outside `REMOVED`
        and reads `NONE` when the arena has no such sheet; its possible values are `NONE`,
        `BUILDING`, `IN_SERVICE`, `COVERED` and `MELTING`."

        Design: Difficulty/dual_variant_calc/turnaround_planned_variant_blind_to_rework_and_idle_minutes_while_actual_absorbs_them
        """
        arena = setup_covering_turnaround_ready_for_signoff()
        signed = signoff_order(arena["order"]["id"], "dir-lakeside")

        assert signed["status"] == "SIGNED_OFF"
        assert signed["signed_off_by_user_id"] == "dir-lakeside"
        assert signed["overrun_minutes"] == 15, "750 actual minutes against a 735 window"

        venue = read_venue(arena["venue_id"])
        assert venue["changeover_debt_minutes"] == 15
        assert venue["ice_deck_status"] == "NONE", (
            "this arena never had an ice sheet flooded on it"
        )


class TestProgressRequiresAConfirmedIncomingShow:
    def test_the_floor_dimension_cannot_start_while_the_incoming_show_is_only_held(
        self, api
    ):
        """PRD §3.8: "Independently of stage legality, the incoming booking must already be
        `CONFIRMED` before any progress at all may be recorded on any dimension — a merely
        held incoming show is not a commitment worth converting a building for — and a
        progress call against an unconfirmed incoming booking is refused with
        `ERR_INCOMING_BOOKING_NOT_CONFIRMED`."
        PRD §3.7: "A newly opened order has `status` reading `PLANNED`, all three of
        `floor_stage`, `seating_stage` and `infra_stage` sitting at `NOT_STARTED`,
        `actual_turnaround_minutes` unset, `overrun_minutes` at 0, `rework_count` at 0,
        `started_at_utc` and `completed_at_utc` unset, `signed_off_by_user_id` unset,
        `abandon_reason` unset, and `opened_by_user_id` recorded as the supervisor's
        `X-User-ID` — the value that segregation of duties will later compare against at
        sign-off."

        Design: Difficulty/cross_entity_state_dependency/floor_dimension_cannot_start_until_the_incoming_booking_leaves_held_for_confirmed
        """
        arena = _turnaround_with_merely_held_incoming()
        assert arena["order"]["planned_turnaround_minutes"] == 708

        response = api.progress_changeover_order(
            arena["order"]["id"],
            {"dimension": "FLOOR", "to_stage": "STRIKING"},
            SUPERVISOR,
        )
        validate_error(
            response, ApiErrorId.ERR_INCOMING_BOOKING_NOT_CONFIRMED.value, 409
        )

        order = read_order(arena["order"]["id"])
        assert order["status"] == "PLANNED"
        assert order["floor_stage"] == "NOT_STARTED"
        assert order["started_at_utc"] is None

    def test_the_identical_progress_call_is_accepted_once_the_incoming_show_is_confirmed(
        self, api
    ):
        """PRD §3.8: "Independently of stage legality, the incoming booking must already be
        `CONFIRMED` before any progress at all may be recorded on any dimension — a merely
        held incoming show is not a commitment worth converting a building for — and a
        progress call against an unconfirmed incoming booking is refused with
        `ERR_INCOMING_BOOKING_NOT_CONFIRMED`."
        PRD §3.8: "The first progress call accepted on an order stamps `started_at_utc` with
        the logical clock instant and moves the compound `status` from `PLANNED` to
        `IN_PROGRESS`."
        PRD §2.5: "The clock's startup value is exactly `2026-08-01T00:00:00Z`."

        Design: Difficulty/cross_entity_state_dependency/floor_dimension_cannot_start_until_the_incoming_booking_leaves_held_for_confirmed
        """
        arena = _turnaround_with_merely_held_incoming()
        response = api.progress_changeover_order(
            arena["order"]["id"],
            {"dimension": "FLOOR", "to_stage": "STRIKING"},
            SUPERVISOR,
        )
        validate_error(
            response, ApiErrorId.ERR_INCOMING_BOOKING_NOT_CONFIRMED.value, 409
        )

        confirmed = confirm_booking(arena["to_booking"]["id"], arena["venue_id"])
        assert confirmed["status"] == "CONFIRMED"

        data = validate_success(
            api.progress_changeover_order(
                arena["order"]["id"],
                {"dimension": "FLOOR", "to_stage": "STRIKING"},
                SUPERVISOR,
            ),
            200,
        )
        assert data["floor_stage"] == "STRIKING"
        assert data["seating_stage"] == "NOT_STARTED"
        assert data["infra_stage"] == "NOT_STARTED"
        assert data["status"] == "IN_PROGRESS"
        assert data["started_at_utc"] == "2026-08-01T00:00:00.000Z", (
            "the first accepted progress call stamps the logical clock instant, which "
            "no test call has moved off its startup value"
        )


class TestThreeParallelDimensions:
    def test_the_three_axes_advance_independently_and_a_skipped_stage_is_refused(
        self, api
    ):
        """PRD §3.8: "Each progress call names exactly one `dimension` — `FLOOR`, `SEATING`
        or `INFRA` — and the `to_stage` it should advance to, and it advances exactly one
        stage on exactly that dimension, leaving the other two untouched."
        PRD §3.8: "A `to_stage` that is not the immediate successor of the named dimension's
        current stage is refused with `ERR_INVALID_ORDER_STATE`; crews may not skip stages or
        reach backwards."
        PRD §3.8: "The **floor dimension** tracks the physical playing surface through
        `floor_stage`, which runs `NOT_STARTED → STRIKING → LAYING → FLOOR_COMPLETE`."

        Design: Difficulty/non_linear_state_machine/three_parallel_changeover_dimensions_advance_independently_and_rework_resets_only_one_axis
        """
        arena = _confirmed_turnaround_ready_to_work()
        order_id = arena["order"]["id"]

        progress_order(order_id, "FLOOR", "STRIKING")
        after_seating = progress_order(order_id, "SEATING", "RETRACTING")
        assert after_seating["floor_stage"] == "STRIKING", (
            "advancing the seating axis must leave the floor axis exactly where it was"
        )
        assert after_seating["seating_stage"] == "RETRACTING"
        assert after_seating["infra_stage"] == "NOT_STARTED"

        response = api.progress_changeover_order(
            order_id, {"dimension": "FLOOR", "to_stage": "FLOOR_COMPLETE"}, SUPERVISOR
        )
        validate_error(response, ApiErrorId.ERR_INVALID_ORDER_STATE.value, 409)

        unchanged = read_order(order_id)
        assert unchanged["floor_stage"] == "STRIKING"
        assert unchanged["seating_stage"] == "RETRACTING"
        assert unchanged["rework_count"] == 0

    def test_rework_resets_only_the_named_axis_and_clears_the_completion_stamp(
        self, api
    ):
        """PRD §3.8: "On acceptance that one dimension resets to `NOT_STARTED` while the
        other two keep their stages exactly where they were, `rework_count` rises by one,
        `completed_at_utc` is cleared back to unset, and the compound `status` becomes
        `REWORK`."
        PRD §3.8: "`started_at_utc` is written exactly once in the order's life and is never
        rewritten — not by later progress, and emphatically not by rework."
        PRD §3.8: "The call after which all three dimensions sit at their terminal stages
        simultaneously — `floor_stage` at `FLOOR_COMPLETE`, `seating_stage` at
        `SEATING_COMPLETE` and `infra_stage` at `BROADCAST_READY` — stamps `completed_at_utc`
        with the logical clock instant and moves the order to `READY_FOR_SIGNOFF`."

        Design: Difficulty/non_linear_state_machine/three_parallel_changeover_dimensions_advance_independently_and_rework_resets_only_one_axis
        """
        arena = _confirmed_turnaround_ready_to_work()
        order_id = arena["order"]["id"]

        progress_order(order_id, "FLOOR", "STRIKING")
        progress_order(order_id, "SEATING", "RETRACTING")
        progress_order(order_id, "FLOOR", "LAYING")
        progress_order(order_id, "FLOOR", "FLOOR_COMPLETE")
        progress_order(order_id, "SEATING", "CURTAINING")
        progress_order(order_id, "SEATING", "SEATING_COMPLETE")
        progress_order(order_id, "INFRA", "UTILITY_SET")
        progress_order(order_id, "INFRA", "NETWORK_SET")

        set_clock("2026-09-10T14:00:00Z")
        ready = progress_order(order_id, "INFRA", "BROADCAST_READY")
        assert ready["status"] == "READY_FOR_SIGNOFF"
        assert ready["completed_at_utc"] == "2026-09-10T14:00:00.000Z"

        reworked = rework_order(
            order_id, "FLOOR", "Panel seam failed the floor inspection"
        )

        assert reworked["status"] == "REWORK"
        assert reworked["floor_stage"] == "NOT_STARTED"
        assert reworked["seating_stage"] == "SEATING_COMPLETE"
        assert reworked["infra_stage"] == "BROADCAST_READY"
        assert reworked["rework_count"] == 1
        assert reworked["completed_at_utc"] is None
        assert reworked["started_at_utc"] == "2026-09-10T04:00:00.000Z", (
            "rework must not rewrite the single start stamp"
        )
        assert reworked["planned_turnaround_minutes"] == 708
        assert reworked["actual_turnaround_minutes"] is None


class TestSignoffCascadesIntoTheIceDeck:
    def test_signing_off_a_covering_turnaround_covers_the_in_service_deck(self, api):
        """PRD §3.8: "One further condition applies to **covering changeovers**, meaning
        turnarounds where the outgoing configuration has `requires_ice` set, the incoming
        configuration does not, and the incoming configuration has `ice_cover_required` set:
        if the arena has an ice sheet sitting `IN_SERVICE`, that sheet's freshly recomputed
        `condensation_risk_score` must be strictly below 40.00, otherwise the sign-off is
        refused with `ERR_CONDENSATION_RISK_TOO_HIGH`."
        PRD §3.8: "Separately, on a covering changeover, the arena's `IN_SERVICE` ice sheet is
        automatically driven `IN_SERVICE → COVERED` with all the consequences of §3.6:
        `cover_installed_at_utc` stamped, `cover_cycles` incremented, the score recomputed,
        and the further automatic `COVERED → MELTING` hop when that increment leaves
        `cover_cycles` above 3."
        PRD §3.6: "On acceptance `cover_installed_at_utc` is stamped with the logical clock
        instant and `cover_cycles` rises by one."

        Design: Difficulty/transitive_cascade/signoff_of_a_covering_changeover_cascades_into_ice_cover_and_then_auto_meltout
        """
        arena = _covering_turnaround_over_a_thrice_covered_deck()
        assert arena["ice_sheet"]["cover_cycles"] == 3
        assert float(arena["ice_sheet"]["cover_hours_accumulated"]) == pytest.approx(
            6.0, abs=0.0005
        )
        assert float(arena["ice_sheet"]["condensation_risk_score"]) == pytest.approx(
            2.50, abs=0.005
        )

        signed = signoff_order(arena["order"]["id"], "dir-lakeside")
        assert signed["status"] == "SIGNED_OFF"
        assert signed["signed_off_by_user_id"] == "dir-lakeside"

        sheet = read_ice_sheet(arena["venue_id"], arena["ice_sheet"]["id"])
        assert sheet["cover_cycles"] == 4, (
            "sign-off of a covering turnaround drives one further covering"
        )
        assert sheet["cover_installed_at_utc"] == "2026-09-10T16:30:00.000Z"
        assert float(sheet["cover_hours_accumulated"]) == pytest.approx(
            6.0, abs=0.0005
        ), "covering the deck accumulates no hours until it is uncovered again"

    def test_the_fourth_covering_forced_by_signoff_melts_the_deck_out(self, api):
        """PRD §3.6: "When the increment on an `IN_SERVICE → COVERED` transition leaves
        `cover_cycles` strictly greater than 3 — that is, on the fourth covering — the sheet
        immediately takes a further `COVERED → MELTING` hop in the same operation, without
        any additional request."
        PRD §3.6: "The event-dependency guard described next does **not** apply to that
        automatic hop; the cover-cycle limit overrides calendar convenience."
        PRD §2.11: "`ice_deck_status` mirrors the arena's single ice sheet outside `REMOVED`
        and reads `NONE` when the arena has no such sheet; its possible values are `NONE`,
        `BUILDING`, `IN_SERVICE`, `COVERED` and `MELTING`."
        PRD §3.8: "The arena's `changeover_debt_minutes` rises by exactly this order's
        `overrun_minutes`."

        Design: Difficulty/transitive_cascade/signoff_of_a_covering_changeover_cascades_into_ice_cover_and_then_auto_meltout
        """
        arena = _covering_turnaround_over_a_thrice_covered_deck()
        signed = signoff_order(arena["order"]["id"], "dir-lakeside")

        assert signed["actual_turnaround_minutes"] == 750
        assert signed["planned_turnaround_minutes"] == 708
        assert signed["overrun_minutes"] == 15

        sheet = read_ice_sheet(arena["venue_id"], arena["ice_sheet"]["id"])
        assert sheet["status"] == "MELTING", (
            "the fourth covering forces the melt-out in the same operation"
        )

        venue = read_venue(arena["venue_id"])
        assert venue["ice_deck_status"] == "MELTING"
        assert venue["changeover_debt_minutes"] == 15
