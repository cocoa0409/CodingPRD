"""Difficulty Rule 9 — compensating_invariant.

Tests where a forward action and a compensating action leave a named conserved
quantity intact. Two conserved quantities exercised: Case.status across an
RFE issue/respond cycle, and the active-SCHEDULED biometrics count across a
reschedule.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    set_clock,
    register_applicant,
    create_draft_case,
    file_case,
    schedule_biometrics_for,
    setup_rfe_pending_i130,
    make_applicant_headers,
    make_officer_headers,
    rfe_respond_payload,
    reschedule_biometrics_payload,
)


class TestRfeIssueRespondPreservesCaseStatus:
    """Forward: issue RFE (UNDER_REVIEW → RFE_PENDING).
    Compensating: respond to RFE (RFE_PENDING → UNDER_REVIEW).
    Conserved: Case.status returns to UNDER_REVIEW."""

    def test_case_status_returns_to_under_review_after_full_cycle(self, api):
        """PRD §3.5: "the case's `status` advances from `UNDER_REVIEW` to `RFE_PENDING`"
        PRD §3.6: "the parent case's `status` cascades back to `UNDER_REVIEW` (a back-edge in
        the case lifecycle — and importantly, `rfe_round_count` is not reset)"

        Design: Difficulty/compensating_invariant/rfe_issue_then_respond_preserves_case_rfe_round_count_versus_status_loop
        """
        applicant, case_rfe, rfe, _officer = setup_rfe_pending_i130()
        assert case_rfe["status"] == "RFE_PENDING"  # forward action complete
        headers = make_applicant_headers(applicant["id"])
        res = api.respond_to_rfe(
            rfe["id"],
            rfe_respond_payload(case_rfe["version"], "Submitted doc_a"),
            headers,
        )
        validate_success(res, 200)
        case_after = get_success_data(api.get_case(case_rfe["id"], headers))
        # Conserved invariant: Case.status equals the pre-issuance status.
        assert case_after["status"] == "UNDER_REVIEW"

    def test_rfe_is_responded_after_compensating_action(self, api):
        """PRD §3.6: "the RFE's `status` becomes `RESPONDED`, its `responded_at` is stamped
        to `ClockState.current_utc`"

        Design: Difficulty/compensating_invariant/rfe_issue_then_respond_preserves_case_rfe_round_count_versus_status_loop
        """
        applicant, case_rfe, rfe, officer = setup_rfe_pending_i130()
        headers = make_applicant_headers(applicant["id"])
        api.respond_to_rfe(
            rfe["id"],
            rfe_respond_payload(case_rfe["version"], "Submitted doc_a"),
            headers,
        )
        rfe_after = get_success_data(api.get_rfe(rfe["id"], officer))
        assert rfe_after["status"] == "RESPONDED"


class TestBiometricsReschedulePreservesActiveScheduledCount:
    """Forward: schedule biometrics (count of SCHEDULED for the case == 1).
    Compensating: reschedule (current becomes RESCHEDULED, a new SCHEDULED is
    created).
    Conserved: count of SCHEDULED biometrics for this case remains == 1."""

    def test_reschedule_preserves_exactly_one_scheduled_for_case(self, api):
        """PRD §3.3: "The current appointment's `status` becomes `RESCHEDULED`, and a fresh
        `BiometricsAppointment` is created in `SCHEDULED` for the same `case_id`
        with the new instant and the new location. The parent case's status
        remains `BIOMETRICS_SCHEDULED`."

        Design: Difficulty/compensating_invariant/biometrics_reschedule_preserves_active_scheduled_appointment_count_versus_status
        """
        set_clock("2026-06-15T00:00:00Z")
        applicant = register_applicant()
        case = create_draft_case(applicant, case_type="I-485")
        filed = file_case(case, applicant)
        officer = make_officer_headers(filed["assigned_officer_id"])
        original = schedule_biometrics_for(filed["id"], officer,
                                           scheduled_at="2026-07-05T15:00:00Z",
                                           asc_location_code="ASC-SF-10")
        # Reschedule it.
        res = api.reschedule_biometrics(
            original["id"],
            reschedule_biometrics_payload("2026-07-10T16:00:00Z", "ASC-SF-11"),
            officer,
        )
        validate_success(res, 200)
        # Original is RESCHEDULED.
        old = get_success_data(api.get_biometrics(original["id"], officer))
        assert old["status"] == "RESCHEDULED"
        # Exactly one SCHEDULED biometrics row remains for this case.
        listing = get_success_data(api.list_biometrics_for_case(filed["id"], officer))
        scheduled = [b for b in listing if b["status"] == "SCHEDULED"]
        assert len(scheduled) == 1, (
            f"Expected exactly one SCHEDULED biometrics for case, got {len(scheduled)}: {scheduled!r}"
        )

    def test_case_status_remains_biometrics_scheduled_after_reschedule(self, api):
        """PRD §3.3: "The parent case's status remains `BIOMETRICS_SCHEDULED`."

        Design: Difficulty/compensating_invariant/biometrics_reschedule_preserves_active_scheduled_appointment_count_versus_status
        """
        set_clock("2026-06-15T00:00:00Z")
        applicant = register_applicant()
        case = create_draft_case(applicant, case_type="I-485")
        filed = file_case(case, applicant)
        officer = make_officer_headers(filed["assigned_officer_id"])
        original = schedule_biometrics_for(filed["id"], officer,
                                           scheduled_at="2026-07-05T15:00:00Z",
                                           asc_location_code="ASC-SF-10")
        api.reschedule_biometrics(
            original["id"],
            reschedule_biometrics_payload("2026-07-10T16:00:00Z", "ASC-SF-11"),
            officer,
        )
        case_after = get_success_data(api.get_case(filed["id"], officer))
        assert case_after["status"] == "BIOMETRICS_SCHEDULED"
