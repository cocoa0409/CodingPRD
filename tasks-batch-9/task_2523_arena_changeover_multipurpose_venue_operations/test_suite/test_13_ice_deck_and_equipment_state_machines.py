"""The ice sheet's hop-by-hop ladder and the arena mirror that follows it, plus
the servicing flag an equipment return bubbles back onto its pool."""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_STARTUP_UTC,
    create_equipment_pool,
    issue_equipment,
    read_asset,
    read_ice_sheet,
    read_issue,
    read_venue,
    return_equipment,
    setup_arena_with_ice_sheet,
    setup_ice_to_concert_turnaround,
    validate_error,
    validate_success,
    venue_version,
    TEST_USERS,
)

SUPERVISOR = TEST_USERS["changeover_supervisor_headers"]


class TestTheIceSheetTransitionLadder:
    def test_a_sheet_still_building_cannot_be_covered_in_one_hop(self, api):
        """PRD §3.6: "A sheet's `status` moves through `BUILDING`, `IN_SERVICE`, `COVERED`,
        `MELTING` and finally `REMOVED`, which is terminal."
        PRD §3.6: "Any `to_status` that is not reachable from the sheet's current `status` is
        refused with `ERR_INVALID_ICE_SHEET_STATE`."
        PRD §3.6: "Those three are combined with weights of 0.45 for the dehumidification
        deficit, 0.30 for the cover load and 0.25 for the thickness deficit; the weighted sum is
        multiplied by 100 and rounded half up to two decimal places to give
        `condensation_risk_score`."
        PRD §2.11: "`ice_deck_status` mirrors the arena's single ice sheet outside `REMOVED` and
        reads `NONE` when the arena has no such sheet; its possible values are `NONE`, `BUILDING`,
        `IN_SERVICE`, `COVERED` and `MELTING`."

        Design: Corner/state_machines/ice_sheet_cannot_transition_from_building_directly_to_covered
        """
        arena = setup_arena_with_ice_sheet(
            dehumidification_lph_applied=120,
            sheet_thickness_mm=32,
            to_status="BUILDING",
            profiles=("ICE",),
        )
        sheet = arena["ice_sheet"]
        assert sheet["status"] == "BUILDING"

        response = api.transition_ice_sheet(
            sheet["id"], {"to_status": "COVERED"}, SUPERVISOR
        )
        validate_error(response, ApiErrorId.ERR_INVALID_ICE_SHEET_STATE.value, 409)

        stored = read_ice_sheet(arena["venue_id"], sheet["id"])
        assert stored["status"] == "BUILDING"
        assert stored["cover_cycles"] == 0
        assert float(stored["condensation_risk_score"]) == pytest.approx(0.00, abs=0.005), (
            "120 of 120 litres per hour and 32 millimetres leave every deficit at zero"
        )
        assert read_venue(arena["venue_id"])["ice_deck_status"] == "BUILDING"

    def test_retiring_the_sheet_frees_the_deck_for_a_fresh_flood(self, api):
        """PRD §3.6: "`MELTING → REMOVED` retires the sheet and sets the arena's
        `ice_deck_status` back to `NONE`."
        PRD §3.6: "The arena must have no existing sheet outside `REMOVED`, otherwise
        `ERR_ICE_SHEET_ALREADY_PRESENT`."
        PRD §3.6: "The new sheet starts with `status` reading `BUILDING`, `cover_cycles` at 0,
        `cover_hours_accumulated` at 0, an initial `condensation_risk_score`, and
        `cover_installed_at_utc` unset."
        PRD §3.6: "Every accepted transition recomputes `condensation_risk_score`, recomputes the
        arena's `ice_deck_status`, and advances the arena's `version` by one — with one exception
        noted below."
        PRD §3.6: "The arena's `ice_deck_status` becomes `BUILDING` and its `version` advances by
        one."

        Design: Corner/state_machines/ice_meltout_to_removed_clears_the_venue_ice_deck_status_to_none
        """
        arena = setup_arena_with_ice_sheet(
            to_status="MELTING", profiles=("ICE",), clock=CLOCK_STARTUP_UTC
        )
        assert read_venue(arena["venue_id"])["ice_deck_status"] == "MELTING"
        version_at_melting = venue_version(arena["venue_id"])

        removed = validate_success(
            api.transition_ice_sheet(
                arena["ice_sheet"]["id"], {"to_status": "REMOVED"}, SUPERVISOR
            ),
            200,
        )
        assert removed["status"] == "REMOVED"
        assert read_venue(arena["venue_id"])["ice_deck_status"] == "NONE"

        replacement = validate_success(
            api.create_ice_sheet(
                arena["venue_id"],
                {
                    "config_profile_id": arena["profiles"]["ICE"]["id"],
                    "dehumidification_lph_applied": 120,
                    "sheet_thickness_mm": 32,
                },
                SUPERVISOR,
            ),
            201,
        )
        assert replacement["status"] == "BUILDING", (
            "a retired sheet no longer occupies the deck"
        )
        assert replacement["cover_cycles"] == 0
        assert replacement["cover_installed_at_utc"] is None

        venue = read_venue(arena["venue_id"])
        assert venue["ice_deck_status"] == "BUILDING"
        assert venue["version"] == version_at_melting + 2, (
            "one bump for the retirement and one for the fresh flood"
        )


class TestTheServicingFlagBubblesUpOnReturn:
    def test_the_interval_th_return_flags_the_pool_while_the_earlier_one_does_not(
        self, api
    ):
        """PRD §3.9: "The pool's `cycles_since_service` rises by one and `service_due` is
        re-evaluated against `service_interval_cycles`."
        PRD §3.9: "`service_due` is likewise derived, and it is evaluated inclusively: the flag is
        true as soon as `cycles_since_service` reaches `service_interval_cycles`, so the
        interval-th cycle already flags the pool rather than the one after it."
        PRD §3.9: "The pool's `units_out_of_service` rises by `damaged_units`, and its
        `units_available` rises by the undamaged remainder — `units_issued` less `damaged_units` —
        so that damaged stock is withdrawn from circulation without disturbing the conserved
        `units_total`."
        PRD §3.9: "On acceptance the issue moves `ISSUED → RETURNED`, `returned_at_utc` is stamped
        with the logical clock instant, and `return_reason` is recorded as `OPERATOR_RETURN`."
        PRD §3.9: "A new pool has `units_available` equal to `units_total`,
        `units_out_of_service` at 0, `cycles_since_service` at 0, `service_due` false and `status`
        reading `IN_SERVICE`, the only alternative being `OUT_OF_SERVICE`."

        Design: Corner/state_machines/equipment_return_bubbles_the_service_due_flag_onto_the_asset
        """
        arena = setup_ice_to_concert_turnaround(crew_headcount=40)
        pool = create_equipment_pool(
            arena["venue_id"], "FLOOR_PANEL_SET", 10, service_interval_cycles=2
        )
        assert pool["service_interval_cycles"] == 2
        first_issue = issue_equipment(pool["id"], arena["order"]["id"], 3)

        first_return = return_equipment(first_issue["id"], damaged_units=1)
        assert first_return["status"] == "RETURNED"
        assert first_return["damaged_units"] == 1
        assert first_return["return_reason"] == "OPERATOR_RETURN"
        assert read_issue(first_issue["id"])["returned_at_utc"] is not None

        after_one = read_asset(pool["id"])
        assert after_one["cycles_since_service"] == 1
        assert after_one["service_due"] is False, "one cycle has not reached two"

        second_issue = issue_equipment(pool["id"], arena["order"]["id"], 2)
        second_return = return_equipment(second_issue["id"], damaged_units=0)
        assert second_return["status"] == "RETURNED"
        assert second_return["damaged_units"] == 0

        after_two = read_asset(pool["id"])
        assert after_two["cycles_since_service"] == 2
        assert after_two["service_due"] is True, (
            "the interval-th cycle already flags the pool"
        )
        assert after_two["units_available"] == 9, (
            "ten units less the one damaged unit, with nothing outstanding"
        )
        assert after_two["units_out_of_service"] == 1
        assert after_two["status"] == "IN_SERVICE", (
            "a due servicing flag does not itself take the pool out of service"
        )
