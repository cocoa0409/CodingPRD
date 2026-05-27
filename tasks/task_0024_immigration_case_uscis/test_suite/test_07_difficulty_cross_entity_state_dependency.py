"""Difficulty Rule 7 — cross_entity_state_dependency.

Tests where one entity's transition is gated by another entity's current state:
Case interview scheduling requires VisaBulletin to be CURRENT, and Case
advance-review requires its BiometricsAppointment to be COMPLETED.
"""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    set_clock,
    publish_visa_bulletin,
    register_applicant,
    create_draft_case,
    file_case,
    schedule_biometrics_for,
    setup_biometrics_scheduled_i485,
    make_officer_headers,
    schedule_interview_payload,
)


class TestCaseInterviewRequiresVisaBulletinCurrent:
    """For an I-485 case, scheduling an interview requires the FINAL_ACTION
    bulletin entry at the current month to be CURRENT (priority_date <
    cutoff_date OR cutoff_date == 'CURRENT'). Otherwise ERR_VISA_RETROGRESSED."""

    def test_interview_rejected_when_visa_retrogressed(self, api):
        """PRD §3.5: "the cross-aggregate visa availability gate must be satisfied: for an
        I-485 case whose `preference_category` is set, visa availability under the
        `FINAL_ACTION` chart at the evaluation month derived from `scheduled_at` must
        be `CURRENT` — concretely, the case's `priority_date` is strictly less than
        the `cutoff_date` of the corresponding `VisaBulletinEntry` for the
        applicant's `country_of_chargeability`, or that `cutoff_date` equals the
        literal `CURRENT`. A retrogressed bulletin month is rejected with `ERR_VISA_RETROGRESSED`."

        Design: Difficulty/cross_entity_state_dependency/case_interview_requires_visabulletin_current_pair_case_visabulletin
        """
        # Set up I-485 case, then publish a deeply retrogressed bulletin entry.
        set_clock("2026-06-15T00:00:00Z")
        publish_visa_bulletin("2026-06", "F2B", "CHINA",
                              "FINAL_ACTION", "2020-01-01")
        applicant = register_applicant(country_of_chargeability="CHINA")
        case = create_draft_case(applicant, case_type="I-485",
                                 preference_category="F2B")
        filed = file_case(case, applicant)
        # priority_date will be 2026-06-15; the cutoff is 2020-01-01 → RETROGRESSED.
        officer = make_officer_headers(filed["assigned_officer_id"])
        biom = schedule_biometrics_for(filed["id"], officer,
                                       scheduled_at="2026-06-25T15:00:00Z",
                                       asc_location_code="ASC-SF-05")
        set_clock("2026-06-26T00:00:00Z")
        get_success_data(api.complete_biometrics(biom["id"], officer))
        get_success_data(api.advance_review(filed["id"], officer))

        res = api.schedule_interview(
            filed["id"],
            schedule_interview_payload("2026-07-10T16:00:00Z", "FO-SFR"),
            officer,
        )
        validate_error(res, "ERR_VISA_RETROGRESSED")

    def test_case_remains_under_review_when_interview_rejected(self, api):
        """PRD §2.10: "no state is mutated" (on failed validation; corollary: the case
        should remain in its prior state when the interview gate fires)
        PRD §3.5: "A retrogressed bulletin month is rejected with `ERR_VISA_RETROGRESSED`."

        Design: Difficulty/cross_entity_state_dependency/case_interview_requires_visabulletin_current_pair_case_visabulletin
        """
        set_clock("2026-06-15T00:00:00Z")
        publish_visa_bulletin("2026-06", "F2B", "CHINA",
                              "FINAL_ACTION", "2020-01-01")
        applicant = register_applicant(country_of_chargeability="CHINA")
        case = create_draft_case(applicant, case_type="I-485",
                                 preference_category="F2B")
        filed = file_case(case, applicant)
        officer = make_officer_headers(filed["assigned_officer_id"])
        biom = schedule_biometrics_for(filed["id"], officer,
                                       scheduled_at="2026-06-25T15:00:00Z",
                                       asc_location_code="ASC-SF-05")
        set_clock("2026-06-26T00:00:00Z")
        get_success_data(api.complete_biometrics(biom["id"], officer))
        get_success_data(api.advance_review(filed["id"], officer))

        api.schedule_interview(
            filed["id"],
            schedule_interview_payload("2026-07-10T16:00:00Z", "FO-SFR"),
            officer,
        )
        case_after = get_success_data(api.get_case(filed["id"], officer))
        assert case_after["status"] == "UNDER_REVIEW"


class TestCaseAdvanceReviewRequiresBiometricsCompleted:
    """advance-review on a BIOMETRICS_SCHEDULED case (whose Biometrics is still
    SCHEDULED) fails ERR_INVALID_STATE."""

    def test_advance_review_rejected_when_biometrics_still_scheduled(self, api):
        """PRD §3.3: "After biometrics are completed, an officer advances the case from
        `BIOMETRICS_COMPLETED` to `UNDER_REVIEW` via the advance-review capability.
        The only precondition is that the case is in `BIOMETRICS_COMPLETED`."

        Design: Difficulty/cross_entity_state_dependency/case_advance_review_requires_biometrics_completed_pair_case_biometricsappointment
        """
        applicant, case, biom, officer = setup_biometrics_scheduled_i485(
            asc_location_code="ASC-SF-06",
        )
        # Case is in BIOMETRICS_SCHEDULED; child biometrics is SCHEDULED.
        # Advance-review requires BIOMETRICS_COMPLETED — should fail.
        res = api.advance_review(case["id"], officer)
        validate_error(res, "ERR_INVALID_STATE")
        # Verify nothing moved.
        case_after = get_success_data(api.get_case(case["id"], officer))
        assert case_after["status"] == "BIOMETRICS_SCHEDULED"

    def test_biometrics_appointment_unchanged_after_failed_advance_review(self, api):
        """PRD §2.10 (precondition-failure contract): "no state is mutated"

        Design: Difficulty/cross_entity_state_dependency/case_advance_review_requires_biometrics_completed_pair_case_biometricsappointment
        """
        applicant, case, biom, officer = setup_biometrics_scheduled_i485(
            asc_location_code="ASC-SF-06",
        )
        api.advance_review(case["id"], officer)
        biom_after = get_success_data(api.get_biometrics(biom["id"], officer))
        assert biom_after["status"] == "SCHEDULED"
