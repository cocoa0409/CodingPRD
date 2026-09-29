"""The ice deck: flooding a sheet, the covering cycle and its condensation
gate, the cover-cycle ceiling and the guarded melt-out."""
import pytest

from test_helpers import (
    ApiErrorId,
    draft_booking,
    install_ice_sheet,
    place_hold,
    read_booking,
    read_ice_sheet,
    read_venue,
    release_booking,
    set_clock,
    setup_arena,
    transition_ice_sheet,
    validate_error,
    validate_success,
    TEST_USERS,
)

SUPERVISOR = TEST_USERS["changeover_supervisor_headers"]


def _sheet_in_service(dehumidification_lph_applied=120, sheet_thickness_mm=32):
    arena = setup_arena(profiles=("ICE", "CONCERT"))
    sheet = install_ice_sheet(
        arena["venue_id"], arena["profiles"]["ICE"]["id"],
        dehumidification_lph_applied=dehumidification_lph_applied,
        sheet_thickness_mm=sheet_thickness_mm,
    )
    arena["sheet_at_install"] = sheet
    arena["sheet"] = transition_ice_sheet(sheet["id"], "IN_SERVICE")
    return arena


def _arena_with_three_holds_around_the_build_window():
    """One ice show starting exactly twelve hours out, one starting a minute
    later, and a concert inside the window that does not need ice at all."""
    arena = _sheet_in_service()
    venue_id = arena["venue_id"]
    edge = draft_booking(
        venue_id, arena["profiles"]["ICE"]["id"], "Edge ice show",
        "2026-08-01T12:00:00Z", "2026-08-01T15:00:00Z",
        expected_attendance=15_000, rigging_load_kg=1_000,
        promoter_name="Lakeside Hockey Club",
    )
    arena["edge_booking"] = place_hold(edge["id"])
    later = draft_booking(
        venue_id, arena["profiles"]["ICE"]["id"], "Later ice show",
        "2026-08-01T12:01:00Z", "2026-08-01T15:01:00Z",
        expected_attendance=15_000, rigging_load_kg=1_000,
        promoter_name="Riverton Athletics",
    )
    arena["later_booking"] = place_hold(later["id"])
    decoy = draft_booking(
        venue_id, arena["profiles"]["CONCERT"]["id"], "Decoy concert",
        "2026-08-01T06:00:00Z", "2026-08-01T09:00:00Z",
        expected_attendance=8_000, rigging_load_kg=1_000,
        promoter_name="Northline Live",
    )
    arena["decoy_booking"] = place_hold(decoy["id"])
    return arena


class TestCoverCycleTerminatesInAutoMeltout:
    def test_uncovering_accumulates_the_cover_hours_and_lifts_the_score(self, api):
        """PRD §3.6: "The elapsed cover period — the hours from `cover_installed_at_utc` to
        the logical clock instant, carried to three decimal places — is added to
        `cover_hours_accumulated`, and `cover_installed_at_utc` is cleared."
        PRD §3.6: "The **cover load** is `cover_hours_accumulated` divided by 72 hours — three
        full days of accumulated cover — capped at one, so a sheet that has spent 72 hours or
        more under panels over its lifetime contributes the maximum."
        PRD §3.6: "Those three are combined with weights of 0.45 for the dehumidification
        deficit, 0.30 for the cover load and 0.25 for the thickness deficit; the weighted sum
        is multiplied by 100 and rounded half up to two decimal places to give
        `condensation_risk_score`."

        Design: Difficulty/non_linear_state_machine/ice_sheet_cover_uncover_cycle_terminates_by_auto_meltout_on_the_fourth_cover
        """
        arena = _sheet_in_service()
        sheet_id = arena["sheet"]["id"]

        transition_ice_sheet(sheet_id, "COVERED")
        set_clock("2026-08-01T02:00:00Z")
        uncovered = transition_ice_sheet(sheet_id, "IN_SERVICE")

        assert uncovered["status"] == "IN_SERVICE"
        assert float(uncovered["cover_hours_accumulated"]) == pytest.approx(
            2.0, abs=0.0005
        )
        assert float(uncovered["condensation_risk_score"]) == pytest.approx(
            0.83, abs=0.005
        ), "two of seventy-two cover hours weighted at 0.30 gives 0.8333, rounded to 0.83"
        assert uncovered["cover_cycles"] == 1

    def test_the_fourth_covering_drives_the_sheet_straight_into_meltout(self, api):
        """PRD §3.6: "A sheet may be covered three times."
        PRD §3.6: "When the increment on an `IN_SERVICE → COVERED` transition leaves
        `cover_cycles` strictly greater than 3 — that is, on the fourth covering — the sheet
        immediately takes a further `COVERED → MELTING` hop in the same operation, without any
        additional request."
        PRD §3.6: "On acceptance `cover_installed_at_utc` is stamped with the logical clock
        instant and `cover_cycles` rises by one."
        PRD §2.11: "`ice_deck_status` mirrors the arena's single ice sheet outside `REMOVED`
        and reads `NONE` when the arena has no such sheet; its possible values are `NONE`,
        `BUILDING`, `IN_SERVICE`, `COVERED` and `MELTING`."

        Design: Difficulty/non_linear_state_machine/ice_sheet_cover_uncover_cycle_terminates_by_auto_meltout_on_the_fourth_cover
        """
        arena = _sheet_in_service()
        sheet_id = arena["sheet"]["id"]

        for hour in (2, 4, 6):
            transition_ice_sheet(sheet_id, "COVERED")
            set_clock(f"2026-08-01T{hour:02d}:00:00Z")
            uncovered = transition_ice_sheet(sheet_id, "IN_SERVICE")
        assert uncovered["cover_cycles"] == 3
        assert uncovered["status"] == "IN_SERVICE"

        final = transition_ice_sheet(sheet_id, "COVERED")

        assert final["cover_cycles"] == 4
        assert final["status"] == "MELTING"
        assert float(final["cover_hours_accumulated"]) == pytest.approx(
            6.0, abs=0.0005
        )
        assert float(final["condensation_risk_score"]) == pytest.approx(
            2.50, abs=0.005
        )
        assert final["cover_installed_at_utc"] == "2026-08-01T06:00:00.000Z"
        assert read_venue(arena["venue_id"])["ice_deck_status"] == "MELTING"


class TestCondensationGateAtExactlyForty:
    def test_a_score_of_exactly_forty_is_refused_while_the_install_itself_stands(
        self, api
    ):
        """PRD §3.6: "`IN_SERVICE → COVERED` is the covering half of the cycle, and it is the
        one transition the condensation gate exists to guard: the freshly recomputed
        `condensation_risk_score` must be **strictly below** 40.00, so a score of exactly
        40.00 is refused with `ERR_CONDENSATION_RISK_TOO_HIGH` while 39.99 is accepted."
        PRD §3.6: "And the applied dehumidification must be at least one quarter of the
        profile's `dehumidification_required_lph` — evaluated inclusively, so exactly a
        quarter of the demand passes — otherwise `ERR_DEHUMIDIFICATION_INSUFFICIENT`."
        PRD §3.6: "The install snapshots the profile's moisture demand onto the sheet as
        `required_dehumidification_lph`."

        Design: Difficulty/boundary_precision_check/condensation_score_of_exactly_40_00_blocks_covering_while_39_99_passes_on_a_three_hundredths_dehum_change
        """
        arena = _sheet_in_service(
            dehumidification_lph_applied=30, sheet_thickness_mm=24
        )
        installed = arena["sheet_at_install"]
        assert float(installed["required_dehumidification_lph"]) == pytest.approx(
            120, abs=0.005
        )
        assert float(installed["condensation_risk_score"]) == pytest.approx(
            40.00, abs=0.005
        ), "a quarter of the demand passes the install floor inclusively"

        response = api.transition_ice_sheet(
            arena["sheet"]["id"], {"to_status": "COVERED"}, SUPERVISOR
        )
        validate_error(response, ApiErrorId.ERR_CONDENSATION_RISK_TOO_HIGH.value, 422)

        unchanged = read_ice_sheet(arena["venue_id"], arena["sheet"]["id"])
        assert unchanged["status"] == "IN_SERVICE"
        assert unchanged["cover_cycles"] == 0
        assert unchanged["cover_installed_at_utc"] is None
        assert read_venue(arena["venue_id"])["ice_deck_status"] == "IN_SERVICE"

    def test_three_hundredths_more_dehumidification_in_the_same_call_admits_the_cover(
        self, api
    ):
        """PRD §3.6: "`IN_SERVICE → COVERED` is the covering half of the cycle, and it is the
        one transition the condensation gate exists to guard: the freshly recomputed
        `condensation_risk_score` must be **strictly below** 40.00, so a score of exactly
        40.00 is refused with `ERR_CONDENSATION_RISK_TOO_HIGH` while 39.99 is accepted."
        PRD §3.6: "It is recomputed at install and on every transition call, so a supervisor
        can lower it by raising `dehumidification_lph_applied` in the same request that asks
        to cover the ice."
        PRD §3.6: "On acceptance `cover_installed_at_utc` is stamped with the logical clock
        instant and `cover_cycles` rises by one."

        Design: Difficulty/boundary_precision_check/condensation_score_of_exactly_40_00_blocks_covering_while_39_99_passes_on_a_three_hundredths_dehum_change
        """
        arena = _sheet_in_service(
            dehumidification_lph_applied=30, sheet_thickness_mm=24
        )
        response = api.transition_ice_sheet(
            arena["sheet"]["id"], {"to_status": "COVERED"}, SUPERVISOR
        )
        validate_error(response, ApiErrorId.ERR_CONDENSATION_RISK_TOO_HIGH.value, 422)

        data = validate_success(
            api.transition_ice_sheet(
                arena["sheet"]["id"],
                {"to_status": "COVERED", "dehumidification_lph_applied": 30.03},
                SUPERVISOR,
            ),
            200,
        )
        assert data["status"] == "COVERED"
        assert float(data["dehumidification_lph_applied"]) == pytest.approx(
            30.03, abs=0.005
        )
        assert float(data["condensation_risk_score"]) == pytest.approx(
            39.99, abs=0.005
        ), "39.98875 rounds half up to two decimal places"
        assert data["cover_cycles"] == 1
        assert data["cover_installed_at_utc"] == "2026-08-01T00:00:00.000Z"
        assert float(data["cover_hours_accumulated"]) == pytest.approx(
            0.0, abs=0.0005
        )
        assert read_venue(arena["venue_id"])["ice_deck_status"] == "COVERED"


class TestMeltOutEventDependencyGuard:
    def test_an_ice_show_starting_exactly_twelve_hours_out_vetoes_the_meltout(self, api):
        """PRD §3.6: "It is refused with `ERR_ICE_EVENT_DEPENDENCY` when any booking on the
        arena whose `status` is `HELD`, `CHALLENGED` or `CONFIRMED`, and whose configuration
        profile has `requires_ice` set, has an `event_start_utc` falling inside the closed
        window that begins at the logical clock instant and ends twelve hours later — twelve
        hours being exactly how long a fresh ice build takes, so the guard refuses to melt out
        ice the building could not rebuild in time."
        PRD §2.5: "The clock's startup value is exactly `2026-08-01T00:00:00Z`."

        Design: Difficulty/cross_entity_state_dependency/ice_meltout_is_vetoed_by_a_booking_whose_start_sits_exactly_on_the_closed_build_window_edge
        """
        arena = _arena_with_three_holds_around_the_build_window()
        assert float(arena["sheet"]["condensation_risk_score"]) == pytest.approx(
            0.00, abs=0.005
        )

        response = api.transition_ice_sheet(
            arena["sheet"]["id"], {"to_status": "MELTING"}, SUPERVISOR
        )
        validate_error(response, ApiErrorId.ERR_ICE_EVENT_DEPENDENCY.value, 409)

        unchanged = read_ice_sheet(arena["venue_id"], arena["sheet"]["id"])
        assert unchanged["status"] == "IN_SERVICE"
        assert read_venue(arena["venue_id"])["ice_deck_status"] == "IN_SERVICE"

    def test_releasing_the_edge_show_admits_the_meltout_over_the_later_ice_show(
        self, api
    ):
        """PRD §3.6: "It is refused with `ERR_ICE_EVENT_DEPENDENCY` when any booking on the
        arena whose `status` is `HELD`, `CHALLENGED` or `CONFIRMED`, and whose configuration
        profile has `requires_ice` set, has an `event_start_utc` falling inside the closed
        window that begins at the logical clock instant and ends twelve hours later — twelve
        hours being exactly how long a fresh ice build takes, so the guard refuses to melt out
        ice the building could not rebuild in time."
        PRD §3.5: "Releasing a `HELD` booking moves it `HELD → RELEASED` and runs the
        dependent cascade in full — reserved dock windows to `RELEASED` with `release_reason`
        of `BOOKING_GONE`, non-terminal changeover orders on either side to `ABANDONED`, and
        from there the equipment returns and labor cancellations of §2.11."
        PRD §2.11: "`open_hold_count` is the number of bookings on the arena whose `status`
        is either `HELD` or `CHALLENGED`."

        Design: Difficulty/cross_entity_state_dependency/ice_meltout_is_vetoed_by_a_booking_whose_start_sits_exactly_on_the_closed_build_window_edge
        """
        arena = _arena_with_three_holds_around_the_build_window()
        response = api.transition_ice_sheet(
            arena["sheet"]["id"], {"to_status": "MELTING"}, SUPERVISOR
        )
        validate_error(response, ApiErrorId.ERR_ICE_EVENT_DEPENDENCY.value, 409)

        released = release_booking(
            arena["edge_booking"]["id"], "Tenant withdrew the edge date"
        )
        assert released["status"] == "RELEASED"

        melting = transition_ice_sheet(arena["sheet"]["id"], "MELTING")
        assert melting["status"] == "MELTING"
        assert float(melting["condensation_risk_score"]) == pytest.approx(
            0.00, abs=0.005
        )

        assert read_booking(arena["later_booking"]["id"])["status"] == "HELD", (
            "a start one minute past the closed window edge never vetoed anything"
        )
        assert read_booking(arena["decoy_booking"]["id"])["status"] == "HELD"

        venue = read_venue(arena["venue_id"])
        assert venue["ice_deck_status"] == "MELTING"
        assert venue["open_hold_count"] == 2
