"""Cross-entity state dependencies: medical-decision requires application in
MEDICAL_REVIEW; CDR start requires application AWARDED + scheduled date due."""
import pytest
from test_helpers import (
    validate_error, get_success_data, api_client, TEST_USERS,
    set_clock,
    create_claimant, create_application_for_claimant,
    attach_evidence,
    setup_application_awarded,
    fetch_cdr_for_award,
    medical_decision_payload,
    make_claimant_headers,
)


# =========================================================================
# Instance: medical_decision_requires_application_in_medical_review
# =========================================================================

class TestMedicalDecisionRequiresApplicationInMedicalReview:
    """The medical-decision endpoint depends on Application.status ==
    MEDICAL_REVIEW. A DRAFT application returns ERR_INVALID_APPLICATION_STATE."""

    def test_medical_decision_on_draft_application_returns_invalid_state(self, api):
        """PRD §3.4: "The application must be in `MEDICAL_REVIEW`,
        otherwise the request is rejected with
        `ERR_INVALID_APPLICATION_STATE`."

        Design: Difficulty/cross_entity_state_dependency/medical_decision_requires_application_in_medical_review
        """
        set_clock("2026-01-15T00:00:00Z")
        claimant = create_claimant(
            ssn_last4="1111",
            full_name="Draft App",
            date_of_birth="1980-01-01T00:00:00Z",
            filing_state="TX",
        )
        app = create_application_for_claimant(
            claimant["id"],
            alleged_onset_date="2024-01-01T00:00:00Z",
            protective_filing_date="2026-01-15T00:00:00Z",
            claim_type="SSDI_ONLY",
        )
        attach_evidence(app["id"], claimant_id=claimant["id"])
        payload = medical_decision_payload(
            decision_type="RFC_DISABLED",
            established_onset_date="2024-01-15T00:00:00Z",
            expected_application_version=app["version"],
            rfc_score=30,
        )
        res = api_client.medical_decision(app["id"], payload, TEST_USERS["dds_examiner_headers"])
        validate_error(res, "ERR_INVALID_APPLICATION_STATE", expected_status=409)

    def test_medical_decision_on_denied_qc_returns_invalid_state(self, api):
        """PRD §3.4: "The application must be in `MEDICAL_REVIEW`,
        otherwise the request is rejected with
        `ERR_INVALID_APPLICATION_STATE`."

        Design: Difficulty/cross_entity_state_dependency/medical_decision_requires_application_in_medical_review
        """
        set_clock("2026-01-15T00:00:00Z")
        # Young claimant with insufficient credits → submit → DENIED_QC.
        claimant = create_claimant(
            ssn_last4="1112",
            full_name="DQ App",
            date_of_birth="2002-06-01T00:00:00Z",
            filing_state="TX",
        )
        app = create_application_for_claimant(
            claimant["id"],
            alleged_onset_date="2025-01-01T00:00:00Z",
            protective_filing_date="2026-01-15T00:00:00Z",
        )
        # Submit with no credits → NOT_INSURED → DENIED_QC.
        res = api_client.submit_application(app["id"], make_claimant_headers(claimant["id"]))
        app_after = get_success_data(res)
        assert app_after["status"] == "DENIED_QC"
        attach_evidence(app["id"])  # as DDSExaminer
        payload = medical_decision_payload(
            decision_type="RFC_DISABLED",
            established_onset_date="2025-01-15T00:00:00Z",
            expected_application_version=app_after["version"],
            rfc_score=30,
        )
        res = api_client.medical_decision(app["id"], payload, TEST_USERS["dds_examiner_headers"])
        validate_error(res, "ERR_INVALID_APPLICATION_STATE", expected_status=409)


# =========================================================================
# Instance: cdr_start_requires_hearing_application_in_awarded_not_alj_pending
# =========================================================================

class TestCdrStartRequiresApplicationInAwardedAndScheduledReviewDateInPast:
    """CDR /start depends on (a) application in AWARDED and (b) the CDR's
    scheduled_review_date already reached. Starting too early yields
    ERR_CDR_NOT_DUE."""

    def test_cdr_start_before_scheduled_review_date_returns_not_due(self, api):
        """PRD §3.9: "A CDR cannot be started until it is due: an
        `SSAAdmin` who attempts to start a review whose
        `scheduled_review_date` lies strictly in the future is rejected
        with `ERR_CDR_NOT_DUE` (409)."

        Design: Difficulty/cross_entity_state_dependency/cdr_start_requires_hearing_application_in_awarded_not_alj_pending
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_application_awarded(
            claimant_overrides={
                "ssn_last4": "2222",
                "full_name": "CDR Early",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
            application_overrides={
                "alleged_onset_date": "2024-01-01T00:00:00Z",
                "protective_filing_date": "2026-01-15T00:00:00Z",
                "claim_type": "SSDI_ONLY",
            },
        )
        cdr = fetch_cdr_for_award(ctx["award"]["id"])
        # CDR was scheduled for ~18 months from medical-decision date;
        # we do NOT advance the clock, so scheduled_review_date is in
        # the future relative to NOW=2026-01-15.
        res = api_client.start_cdr(cdr["id"], TEST_USERS["ssa_admin_headers"])
        validate_error(res, "ERR_CDR_NOT_DUE", expected_status=409)

    def test_cdr_start_succeeds_when_due_date_reached(self, api):
        """PRD §3.9: "Starting a due review requires the parent
        application to be in `AWARDED` and transitions the application to
        `CDR_FROZEN`, signalling that no benefit changes are accepted
        while the review is in flight; the application's `version`
        increments."

        Design: Difficulty/cross_entity_state_dependency/cdr_start_requires_hearing_application_in_awarded_not_alj_pending
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_application_awarded(
            claimant_overrides={
                "ssn_last4": "2223",
                "full_name": "CDR On Time",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
            application_overrides={
                "alleged_onset_date": "2024-01-01T00:00:00Z",
                "protective_filing_date": "2026-01-15T00:00:00Z",
                "claim_type": "SSDI_ONLY",
            },
        )
        cdr = fetch_cdr_for_award(ctx["award"]["id"])
        # Advance past 18-month MIE schedule.
        set_clock("2028-01-15T00:00:00Z")
        res = api_client.start_cdr(cdr["id"], TEST_USERS["ssa_admin_headers"])
        data = get_success_data(res)
        # Application should now be CDR_FROZEN.
        res = api_client.get_application(ctx["application"]["id"], TEST_USERS["ssa_admin_headers"])
        app_after = get_success_data(res)
        assert app_after["status"] == "CDR_FROZEN", \
            f"Expected CDR_FROZEN after CDR start, got {app_after['status']}"
