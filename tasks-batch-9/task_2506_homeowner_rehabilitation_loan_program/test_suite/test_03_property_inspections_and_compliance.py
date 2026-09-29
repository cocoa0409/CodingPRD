"""Site visits, the lead action level, and the two independent case axes."""

import pytest

from test_helpers import (
    api_client,
    assert_instant,
    assert_property_inspection,
    assert_two_axes,
    create_inspection_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    INSPECTOR,
    INSPECTOR_2,
    approve_write_up,
    build_ownership_verified_application,
    build_verified_applicant,
    clear_historic_review,
    clear_lead_review,
    open_solicitation,
    record_result,
    refresh_application,
    refresh_inspection,
    schedule_inspection,
    setup_historic_case,
)

LEAD_HAZARD_LINE = {
    "description": "Enclosure of lead-painted trim",
    "category": "LEAD_HAZARD_CONTROL",
    "priority_class": "HEALTH_SAFETY",
    "estimated_cost_cents": 1_000_000,
    "is_lead_hazard_reduction": True,
    "is_historic_sensitive": False,
}


def _inspections_on(application_id):
    inspections, _ = validate_paginated(
        api_client.list_inspections(INSPECTOR, {"application_id": application_id})
    )
    return inspections


class TestLeadActionLevel:
    """1.00 milligrams per square centimetre is an inclusive threshold."""

    def _verified_dwelling(self, program_year, address_line1):
        applicant = build_verified_applicant(program_year["id"])
        return build_ownership_verified_application(
            applicant["id"], address_line1=address_line1
        )

    def test_a_reading_just_below_the_action_level_records_no_lead_hazard(
        self, program_year
    ):
        """0.99 milligrams per square centimetre stays under the action level.

        PRD: "The row moves `SCHEDULED → COMPLETED`, stores all three values,
        sets `lead_hazard_present` true exactly when the recorded reading is at
        or above the action level of 1.00 milligrams per square centimetre, and
        advances its `version` by one."

        Design: Difficulty/boundary_precision_check/xrf_reading_of_exactly_one_milligram_per_square_centimeter_is_a_lead_hazard
        """
        application = self._verified_dwelling(program_year, "31 Bellow St")
        inspection = schedule_inspection(application["id"])

        recorded = record_result(
            inspection["id"], result="FAIL", deficiency_count=2, xrf_reading_mg_cm2=0.99
        )

        assert_property_inspection(recorded)
        assert recorded["xrf_reading_mg_cm2"] == pytest.approx(0.99, abs=0.001)
        assert recorded["lead_hazard_present"] is False, (
            "A reading below 1.00 leaves the hazard flag false, got "
            f"{recorded['lead_hazard_present']}"
        )
        assert recorded["status"] == "COMPLETED"
        case = refresh_application(application["id"])
        assert case["lead_hazard_detected"] is False
        assert_two_axes(case, "INSPECTED", "CLEAR")

    def test_a_reading_exactly_at_the_action_level_records_a_lead_hazard(
        self, program_year
    ):
        """Exactly 1.00 milligrams per square centimetre is a hazard.

        PRD: "Independently of the deficiency branch, an `INITIAL_STANDARDS`
        visit whose reading is at or above 1.00 milligrams per square centimetre
        sets `lead_hazard_detected` true on the case."

        Design: Difficulty/boundary_precision_check/xrf_reading_of_exactly_one_milligram_per_square_centimeter_is_a_lead_hazard
        """
        application = self._verified_dwelling(program_year, "33 Bellow St")
        inspection = schedule_inspection(application["id"])

        recorded = record_result(
            inspection["id"], result="FAIL", deficiency_count=2, xrf_reading_mg_cm2=1.00
        )

        assert recorded["xrf_reading_mg_cm2"] == pytest.approx(1.00, abs=0.001)
        assert recorded["lead_hazard_present"] is True, (
            "A reading at the action level sets the hazard flag true, got "
            f"{recorded['lead_hazard_present']}"
        )
        assert recorded["status"] == "COMPLETED"
        case = refresh_application(application["id"])
        assert case["lead_hazard_detected"] is True
        # A 1995 build year requires no lead protocol, so the reading is
        # recorded without gating the case.
        assert_two_axes(case, "INSPECTED", "CLEAR")


class TestInspectionWindows:
    """Reserved windows are half-open intervals scoped to one dwelling."""

    def test_an_interior_overlap_on_one_dwelling_is_refused(
        self, ownership_verified_application
    ):
        """A window that starts inside a reserved window conflicts.

        PRD: "A window that begins exactly when an existing window ends is
        accepted; any interior overlap is refused with
        `ERR_INSPECTION_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/inspection_windows_on_one_property_are_half_open_so_touching_windows_are_allowed
        """
        application_id = ownership_verified_application["id"]
        first = schedule_inspection(
            application_id,
            scheduled_start_at="2026-08-03T13:00:00Z",
            scheduled_end_at="2026-08-03T15:00:00Z",
        )

        response = api_client.create_inspection(
            create_inspection_payload(
                application_id,
                scheduled_start_at="2026-08-03T14:00:00Z",
                scheduled_end_at="2026-08-03T16:00:00Z",
            ),
            INSPECTOR_2,
        )

        validate_error(response, "ERR_INSPECTION_WINDOW_CONFLICT")
        assert len(_inspections_on(application_id)) == 1, (
            "A refused reservation writes no inspection row"
        )
        assert refresh_inspection(first["id"])["status"] == "SCHEDULED"

    def test_a_window_that_begins_when_another_ends_is_accepted(
        self, ownership_verified_application
    ):
        """Touching windows do not collide, because the end instant is excluded.

        PRD: "Each reserved window is treated as a half-open interval that
        includes its start instant and excludes its end instant, and the new
        window is compared against every `SCHEDULED` and `COMPLETED` inspection
        already on the same case."

        Design: Difficulty/resource_temporal_overlap/inspection_windows_on_one_property_are_half_open_so_touching_windows_are_allowed
        """
        application_id = ownership_verified_application["id"]
        first = schedule_inspection(
            application_id,
            scheduled_start_at="2026-08-03T13:00:00Z",
            scheduled_end_at="2026-08-03T15:00:00Z",
        )

        second = validate_success(
            api_client.create_inspection(
                create_inspection_payload(
                    application_id,
                    scheduled_start_at="2026-08-03T15:00:00Z",
                    scheduled_end_at="2026-08-03T17:00:00Z",
                ),
                INSPECTOR_2,
            ),
            201,
        )

        assert_instant(second, "scheduled_start_at", "2026-08-03T15:00:00Z")
        assert second["status"] == "SCHEDULED"
        assert len(_inspections_on(application_id)) == 2
        untouched = refresh_inspection(first["id"])
        assert_instant(untouched, "scheduled_start_at", "2026-08-03T13:00:00Z")
        assert_instant(untouched, "scheduled_end_at", "2026-08-03T15:00:00Z")
        assert untouched["status"] == "SCHEDULED"

    def test_the_window_conflict_is_scoped_to_one_dwelling(self, program_year):
        """An identical window on another dwelling is not a collision.

        PRD: "Windows on the same dwelling may not collide."

        Design: Difficulty/resource_temporal_overlap/inspection_windows_on_one_property_are_half_open_so_touching_windows_are_allowed
        """
        applicant = build_verified_applicant(program_year["id"])
        first_dwelling = build_ownership_verified_application(
            applicant["id"], address_line1="41 Bellow St"
        )
        second_dwelling = build_ownership_verified_application(
            applicant["id"], address_line1="43 Bellow St"
        )
        window = {
            "scheduled_start_at": "2026-08-03T13:00:00Z",
            "scheduled_end_at": "2026-08-03T15:00:00Z",
        }
        schedule_inspection(first_dwelling["id"], **window)

        accepted = validate_success(
            api_client.create_inspection(
                create_inspection_payload(second_dwelling["id"], **window),
                INSPECTOR,
            ),
            201,
        )

        assert accepted["application_id"] == second_dwelling["id"]
        assert accepted["status"] == "SCHEDULED"
        assert len(_inspections_on(first_dwelling["id"])) == 1
        assert len(_inspections_on(second_dwelling["id"])) == 1


class TestParallelAxes:
    """One case row carries a workflow axis and a compliance axis at once."""

    @pytest.fixture
    def dual_hold_case(self):
        """A 1962 historic-district case with a submitted lead-hazard scope."""
        return setup_historic_case(
            stage="writeup_submitted",
            clear_compliance=False,
            lines=[LEAD_HAZARD_LINE],
        )

    def test_the_lead_clearance_moves_the_compliance_axis_alone(self, dual_hold_case):
        """Clearing lead on a dual-hold case leaves the workflow axis untouched.

        PRD: "From `DUAL_HOLD`, a completed risk assessment moves the posture
        `DUAL_HOLD → HISTORIC_HOLD`, leaving the historic axis outstanding; this
        path additionally requires that the case's `workflow_state` be one of
        `INSPECTED`, `WRITEUP_APPROVED`, `BID_OPEN`, `BID_FAILED` or `AWARDED`."

        Design: Difficulty/non_linear_state_machine/application_workflow_and_compliance_axes_advance_independently
        """
        application_id = dual_hold_case["application"]["id"]
        approve_write_up(dual_hold_case["write_up"]["id"])
        assert_two_axes(
            refresh_application(application_id), "WRITEUP_APPROVED", "DUAL_HOLD"
        )

        cleared = clear_lead_review(
            application_id, hazard_control_method="INTERIM_CONTROLS"
        )

        assert_two_axes(cleared, "WRITEUP_APPROVED", "HISTORIC_HOLD")
        assert cleared["lead_hazard_control_method"] == "INTERIM_CONTROLS"
        assert cleared["lead_hazard_detected"] is True

    def test_opening_the_solicitation_moves_the_workflow_axis_alone(
        self, dual_hold_case
    ):
        """The case bids while the historic axis is still outstanding.

        PRD: "Opening the solicitation snapshots
        `independent_cost_estimate_cents` from the write-up's
        `total_estimate_cents` — a frozen figure that later changes to the
        write-up cannot move — computes the responsiveness window described
        below, opens the solicitation in `OPEN` with `bid_count`,
        `responsive_bid_count` and `reopen_count` all zero and `award_bid_id`
        and `awarded_by_user_id` unset, and drives the case `WRITEUP_APPROVED →
        BID_OPEN`, advancing the case `version` by one."

        Design: Difficulty/non_linear_state_machine/application_workflow_and_compliance_axes_advance_independently
        """
        application_id = dual_hold_case["application"]["id"]
        write_up = approve_write_up(dual_hold_case["write_up"]["id"])
        clear_lead_review(application_id, hazard_control_method="INTERIM_CONTROLS")

        solicitation = open_solicitation(
            application_id, write_up["id"], min_bids_required=1
        )

        assert solicitation["independent_cost_estimate_cents"] == 1_265_000, (
            "A single 1,000,000 lead-hazard line loads to 1,150,000 and carries "
            "115,000 of contingency, got "
            f"{solicitation['independent_cost_estimate_cents']}"
        )
        assert_two_axes(refresh_application(application_id), "BID_OPEN", "HISTORIC_HOLD")

    def test_the_historic_clearance_completes_the_compliance_axis_alone(
        self, dual_hold_case
    ):
        """The last clearance lands on `CLEARED_WITH_PROTOCOL` and leaves bidding open.

        PRD: "From `HISTORIC_HOLD` on a case whose `lead_review_required` is
        true, the posture moves `HISTORIC_HOLD → CLEARED_WITH_PROTOCOL`."

        Design: Difficulty/non_linear_state_machine/application_workflow_and_compliance_axes_advance_independently
        """
        application_id = dual_hold_case["application"]["id"]
        write_up = approve_write_up(dual_hold_case["write_up"]["id"])
        clear_lead_review(application_id, hazard_control_method="INTERIM_CONTROLS")
        open_solicitation(application_id, write_up["id"], min_bids_required=1)

        cleared = clear_historic_review(application_id, shpo_review_outcome="CONDITIONS")

        assert_two_axes(cleared, "BID_OPEN", "CLEARED_WITH_PROTOCOL")
        assert cleared["shpo_review_outcome"] == "CONDITIONS"
        assert cleared["lead_hazard_control_method"] == "INTERIM_CONTROLS"
