"""Guards whose deciding state lives on a different row from the one being written."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_created_at_ascending,
    build_bank_scenario,
    build_listed_public_scenario,
    confirm_reservation,
    determine_eligibility,
    expected_post_thaw_dose,
    file_screening,
    make_facilities_engineer_headers,
    make_intake_coordinator_headers,
    make_medical_director_headers,
    nightly_run,
    place_reservation,
    read_listing,
    read_reservation,
    read_screening,
    read_tank,
    read_unit,
    record_confirmatory_test,
    set_clock,
    validate_error,
    validate_success,
)


def _unit_with_an_out_of_window_panel():
    """A characterised private unit whose only panel was drawn 21 days early."""
    return build_bank_scenario(
        stage="tested",
        tank_code=None,
        program_type="PRIVATE_FAMILY",
        primary_parent_name="Screening Parent",
        collection_site_code="SITE-11",
        consent_document_hash="hash-sc-v1",
        kit_lot_code="LOT-2026-S",
        courier_tracking_code="TRK-1100",
        screening_collected_at="2026-07-20T05:00:00Z",
    )


class TestEligibilityGatedOnTheScreeningRowState:
    def test_a_panel_drawn_outside_the_delivery_window_lands_invalid(self):
        """The draw date alone puts the panel beyond use for the rest of its life.

        "if `collected_at` falls outside the window running from 7 days before the enrollment's
        `expected_delivery_date` to 7 days after it — a window whose endpoints are both
        inclusive — the panel's `status` is `INVALID`, `overall_result` is null, and the record
        can never govern eligibility for the rest of its life."

        Design: Difficulty/cross_entity_state_dependency/unit_eligibility_gated_on_maternal_screening_row_state
        """
        scenario = _unit_with_an_out_of_window_panel()

        panel = read_screening(scenario["screening"]["id"])
        assert panel["status"] == "INVALID"
        assert panel["overall_result"] is None
        assert panel["valid_until"].startswith("2027-01-16T05:00:00")

    def test_the_determination_fails_although_a_screening_row_exists(self):
        """An `INVALID` panel is invisible to the governing selection.

        "on eligibility determination, registry publication and release, the enrollment has at
        least one `MaternalScreening` in status `COMPLETED` whose `valid_until` is not in the
        past. Otherwise `ERR_MATERNAL_SCREENING_INCOMPLETE` (409)."

        Design: Difficulty/cross_entity_state_dependency/unit_eligibility_gated_on_maternal_screening_row_state
        """
        scenario = _unit_with_an_out_of_window_panel()

        response = api_client.determine_eligibility(
            scenario["unit"]["id"],
            {"decision_note": "attempt with an out-of-window panel only"},
            make_medical_director_headers("md-001"),
        )

        validate_error(response, ApiErrorId.ERR_MATERNAL_SCREENING_INCOMPLETE.value, 409)

        unit = read_unit(scenario["unit"]["id"])
        assert unit["eligibility_status"] == "PENDING"
        assert unit["eligibility_reason_code"] is None
        assert unit["eligibility_determined_by_user_id"] is None

    def test_filing_an_in_window_panel_is_all_it_takes_to_succeed(self):
        """Nothing on the unit changes between the failure and the success.

        "Panels in `PENDING`, `INVALID` or `EXPIRED` are excluded from that selection entirely,
        which means a newer `INVALID` panel never displaces an older `COMPLETED` one."

        Design: Difficulty/cross_entity_state_dependency/unit_eligibility_gated_on_maternal_screening_row_state
        """
        scenario = _unit_with_an_out_of_window_panel()
        score_before = read_unit(scenario["unit"]["id"])["quality_acceptance_score"]

        api_client.determine_eligibility(
            scenario["unit"]["id"],
            {"decision_note": "attempt with an out-of-window panel only"},
            make_medical_director_headers("md-001"),
        )

        good_panel = file_screening(
            scenario["enrollment"]["id"], collected_at="2026-08-10T05:00:00Z"
        )
        assert good_panel["status"] == "COMPLETED"
        assert good_panel["overall_result"] == "NON_REACTIVE"
        assert good_panel["reactive_marker_codes"] == []

        determine_eligibility(scenario["unit"]["id"], director_user_id="md-001")

        unit = read_unit(scenario["unit"]["id"])
        assert unit["eligibility_status"] == "ELIGIBLE"
        assert unit["eligibility_reason_code"] == "ACCEPTED"
        assert unit["quality_acceptance_score"] == pytest.approx(90.40, abs=0.01)
        assert unit["quality_acceptance_score"] == pytest.approx(score_before, abs=0.01)

    def test_both_panels_remain_readable_in_creation_order(self):
        """The rejected panel is not deleted; it simply never governs.

        "Where an enrollment has several panels, exactly one **governs**: of the panels in
        status `COMPLETED`, ordered by `created_at` ascending, the last one wins."

        Design: Difficulty/cross_entity_state_dependency/unit_eligibility_gated_on_maternal_screening_row_state
        """
        scenario = _unit_with_an_out_of_window_panel()
        file_screening(scenario["enrollment"]["id"], collected_at="2026-08-10T05:00:00Z")

        panels = validate_success(
            api_client.list_enrollment_maternal_screenings(
                scenario["enrollment"]["id"], make_intake_coordinator_headers()
            )
        )

        assert len(panels) == 2
        assert_created_at_ascending(panels)
        assert panels[0]["status"] == "INVALID"
        assert panels[1]["status"] == "COMPLETED"


def _confirmed_hold_in_a_tank_due_for_maintenance():
    """A release-ready hold on a unit stored in a tank with a maintenance window."""
    scenario = build_listed_public_scenario(
        tank_code="TANK-J",
        capacity_slots=5,
        maintenance_window_start="2026-09-10T00:00:00Z",
        maintenance_window_end="2026-09-11T00:00:00Z",
        primary_parent_name="Maintenance Parent",
        collection_site_code="SITE-12",
        consent_document_hash="hash-mt-v1",
        kit_lot_code="LOT-2026-M",
        courier_tracking_code="TRK-1200",
        slot_code="J-01",
        hla_a="A*02:01",
        hla_b="B*08:01",
        hla_drb1="DRB1*03:01",
    )
    set_clock("2026-09-09T00:00:00Z")
    reservation = place_reservation(
        scenario["unit"]["id"],
        center_user_id="tc-001",
        requesting_center_name="Center Maintenance",
        patient_weight_kg=35.0,
        patient_hla_match_count=6,
        hold_from="2026-09-15T00:00:00Z",
        hold_until="2026-09-20T00:00:00Z",
    )
    scenario["reservation"] = confirm_reservation(
        reservation["id"], intended_transplant_date="2026-09-16", center_user_id="tc-001"
    )
    scenario["confirmatory_test"] = record_confirmatory_test(
        scenario["unit"]["id"],
        reservation["id"],
        tnc_millions=1200,
        cd34_thousands=2400,
        viability_pct=82.0,
        volume_ml=24.0,
    )
    return scenario


class TestReleaseGatedOnTheHoldingTankStatus:
    def test_the_nightly_run_walks_the_tank_into_its_window(self):
        """The clock inside the window is what puts the tank into maintenance.

        "A tank in `ONLINE` moves `ONLINE → MAINTENANCE` when the logical clock is at or after
        `maintenance_window_start` and strictly before `maintenance_window_end`."

        Design: Difficulty/cross_entity_state_dependency/release_gated_on_holding_tank_status
        """
        scenario = _confirmed_hold_in_a_tank_due_for_maintenance()

        set_clock("2026-09-10T06:00:00Z")
        counters = nightly_run()

        assert counters["tanks_entered_maintenance"] == 1
        assert counters["tanks_exited_maintenance"] == 0
        assert counters["reservations_expired"] == 0
        assert read_tank(scenario["tank"]["id"])["status"] == "MAINTENANCE"

    def test_the_release_is_refused_by_the_state_of_a_row_it_never_names(self):
        """Every other release gate holds; only the tank's status blocks the shipment.

        "The holding tank's `status` must be `ONLINE`, and an `ALARM`, `MAINTENANCE` or
        `OFFLINE` tank is `ERR_TANK_NOT_OPERATIONAL`."

        Design: Difficulty/cross_entity_state_dependency/release_gated_on_holding_tank_status
        """
        scenario = _confirmed_hold_in_a_tank_due_for_maintenance()

        hold = read_reservation(scenario["reservation"]["id"])
        assert hold["confirmatory_test_id"] == scenario["confirmatory_test"]["id"]
        assert hold["post_thaw_dose_x1e7_per_kg"] == pytest.approx(2.81, abs=0.01)
        assert hold["post_thaw_dose_x1e7_per_kg"] == pytest.approx(
            expected_post_thaw_dose(1500, 1200, 82.0, 35.0), abs=0.01
        )
        assert read_unit(scenario["unit"]["id"])["eligibility_status"] == "ELIGIBLE"

        set_clock("2026-09-10T06:00:00Z")
        nightly_run()

        response = api_client.release_reservation(
            scenario["reservation"]["id"],
            {"release_note": "attempt during tank maintenance"},
            make_medical_director_headers("md-002"),
        )

        validate_error(response, ApiErrorId.ERR_TANK_NOT_OPERATIONAL.value, 409)

    def test_the_refused_release_leaves_hold_unit_listing_and_slot_intact(self):
        """A refused release is not a partial release.

        "**Release for transplant** is the irreversible act, performed by a `MedicalDirector`
        with an optional `release_note`, and it is gated on eight conditions, all of which must
        hold."

        Design: Difficulty/cross_entity_state_dependency/release_gated_on_holding_tank_status
        """
        scenario = _confirmed_hold_in_a_tank_due_for_maintenance()

        set_clock("2026-09-10T06:00:00Z")
        nightly_run()
        api_client.release_reservation(
            scenario["reservation"]["id"],
            {"release_note": "attempt during tank maintenance"},
            make_medical_director_headers("md-002"),
        )

        hold = read_reservation(scenario["reservation"]["id"])
        assert hold["status"] == "CONFIRMED"
        assert hold["released_at"] is None
        assert hold["settlement_total_cents"] is None

        assert read_unit(scenario["unit"]["id"])["availability_status"] == "RESERVED"
        assert read_listing(scenario["listing"]["id"])["listing_status"] == "MATCHED"

        tank = read_tank(scenario["tank"]["id"])
        assert tank["occupied_slots"] == 1
        held = validate_success(
            api_client.list_tank_units(tank["id"], make_facilities_engineer_headers())
        )
        assert len(held) == 1
