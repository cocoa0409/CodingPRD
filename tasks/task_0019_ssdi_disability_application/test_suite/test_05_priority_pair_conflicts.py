"""Validation priority pair conflicts: state vs business_safety;
business_referential vs business_safety."""
import pytest
from test_helpers import (
    validate_error, get_success_data, api_client, TEST_USERS,
    set_clock,
    create_claimant, create_application_for_claimant,
    setup_application_in_medical_review,
    attach_evidence,
    medical_decision_payload,
    make_claimant_headers,
)


# =========================================================================
# Instance: state_vs_business_safety_medical_decision_on_draft_with_bad_eod
# =========================================================================

class TestStateVsBusinessSafetyMedicalDecisionOnDraftWithBadEod:
    """Application is DRAFT (state-check fails) AND payload has EOD<AOD
    (business-safety fails). PRD §2.9 pins the priority: state check fires
    first, returning ERR_INVALID_APPLICATION_STATE."""

    def test_state_check_wins_over_eod_check_on_draft_application(self, api):
        """PRD §2.9: "Once existence is confirmed, the server evaluates
        state preconditions — that the target `Application`'s `status`
        matches the from-state of the requested transition"
        PRD §2.9: "State precondition failures yield
        `ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_HEARING_STATE`, or
        `ERR_CDR_NOT_DUE` as appropriate, each with HTTP status 409."
        PRD §2.9: "Only when all of the preceding gates pass does the
        server evaluate the domain-specific business rules — onset-date
        ordering"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_medical_decision_on_draft_with_bad_eod
        """
        set_clock("2026-01-15T00:00:00Z")
        claimant = create_claimant(
            ssn_last4="6060",
            full_name="Conflict One",
            date_of_birth="1980-01-01T00:00:00Z",
            filing_state="TX",
        )
        # Application created but NOT submitted — stays in DRAFT.
        app = create_application_for_claimant(
            claimant["id"],
            alleged_onset_date="2024-01-01T00:00:00Z",
            protective_filing_date="2026-01-15T00:00:00Z",
            claim_type="SSDI_ONLY",
        )
        attach_evidence(app["id"], claimant_id=claimant["id"])
        # Trigger: bad EOD (2023-06-01 < AOD 2024-01-01) on DRAFT application.
        payload = medical_decision_payload(
            decision_type="RFC_DISABLED",
            established_onset_date="2023-06-01T00:00:00Z",
            expected_application_version=app["version"],
            rfc_score=30,
        )
        res = api_client.medical_decision(app["id"], payload, TEST_USERS["dds_examiner_headers"])
        validate_error(res, "ERR_INVALID_APPLICATION_STATE", expected_status=409)

    def test_eod_check_fires_when_state_matches_isolating_priority(self, api):
        """PRD §3.4: "The examiner's `established_onset_date` must be on
        or after the application's `alleged_onset_date`; an EOD that
        precedes the AOD is rejected with `ERR_EOD_BEFORE_AOD` (422)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_medical_decision_on_draft_with_bad_eod
        """
        set_clock("2026-01-15T00:00:00Z")
        # Application reaches MEDICAL_REVIEW (state OK). Trigger uses
        # current version (no stale check fires). Only EOD<AOD remains.
        claimant, app_submitted = setup_application_in_medical_review(
            claimant_overrides={
                "ssn_last4": "6061",
                "full_name": "Eod Only",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
            application_overrides={
                "alleged_onset_date": "2024-01-01T00:00:00Z",
                "protective_filing_date": "2026-01-15T00:00:00Z",
                "claim_type": "SSDI_ONLY",
            },
        )
        payload = medical_decision_payload(
            decision_type="RFC_DISABLED",
            established_onset_date="2023-06-01T00:00:00Z",  # before AOD
            expected_application_version=app_submitted["version"],
            rfc_score=30,
        )
        res = api_client.medical_decision(app_submitted["id"], payload,
                                           TEST_USERS["dds_examiner_headers"])
        validate_error(res, "ERR_EOD_BEFORE_AOD", expected_status=422)


# =========================================================================
# Instance: business_referential_vs_business_safety_stale_version_with_bad_eod
# =========================================================================

class TestBusinessReferentialVsBusinessSafetyStaleVersionWithBadEod:
    """Application is MEDICAL_REVIEW (state OK) AND payload has both stale
    expected_application_version AND EOD<AOD. PRD §2.9 pins the priority:
    OCC stale-version check fires before business-safety, returning
    ERR_STALE_APPLICATION_VERSION."""

    def test_stale_version_check_wins_over_eod_check(self, api):
        """PRD §2.9: "Optimistic-concurrency stale-version checks (described
        in §2.7) come after state checks and before any business-safety or
        business-temporal rule."
        PRD §2.7: "If that value does not match the `Application`'s
        current `version` at the moment the server processes the write,
        the request is rejected with `ERR_STALE_APPLICATION_VERSION` and
        HTTP status 412."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_safety_stale_version_with_bad_eod
        """
        set_clock("2026-01-15T00:00:00Z")
        claimant, app_submitted = setup_application_in_medical_review(
            claimant_overrides={
                "ssn_last4": "7070",
                "full_name": "Stale Conf",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
            application_overrides={
                "alleged_onset_date": "2024-01-01T00:00:00Z",
                "protective_filing_date": "2026-01-15T00:00:00Z",
                "claim_type": "SSDI_ONLY",
            },
            attach_evidence_after=True,
        )
        # The post-submit version is the live one. Use a strictly smaller
        # number as a stale token (version=1 was the pre-submit value;
        # submit bumped it). Either way, "current - 1" is guaranteed stale.
        stale_version = app_submitted["version"] - 1
        assert stale_version >= 1, "submit must have bumped the version to >= 2"
        # Bad EOD (2023-06-01) AND stale version → stale-version wins.
        payload = medical_decision_payload(
            decision_type="RFC_DISABLED",
            established_onset_date="2023-06-01T00:00:00Z",
            expected_application_version=stale_version,
            rfc_score=30,
        )
        res = api_client.medical_decision(app_submitted["id"], payload, TEST_USERS["dds_examiner_headers"])
        validate_error(res, "ERR_STALE_APPLICATION_VERSION", expected_status=412)

    def test_stale_version_fires_with_valid_eod_isolating_priority(self, api):
        """PRD §2.7: "If that value does not match the `Application`'s
        current `version` at the moment the server processes the write,
        the request is rejected with `ERR_STALE_APPLICATION_VERSION` and
        HTTP status 412."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_safety_stale_version_with_bad_eod
        """
        set_clock("2026-01-15T00:00:00Z")
        claimant, app_submitted = setup_application_in_medical_review(
            claimant_overrides={
                "ssn_last4": "7071",
                "full_name": "Stale Only",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
            application_overrides={
                "alleged_onset_date": "2024-01-01T00:00:00Z",
                "protective_filing_date": "2026-01-15T00:00:00Z",
                "claim_type": "SSDI_ONLY",
            },
        )
        stale_version = app_submitted["version"] - 1
        # Valid EOD (>= AOD); only stale-version error remains.
        payload = medical_decision_payload(
            decision_type="RFC_DISABLED",
            established_onset_date="2024-06-15T00:00:00Z",
            expected_application_version=stale_version,
            rfc_score=30,
        )
        res = api_client.medical_decision(app_submitted["id"], payload,
                                           TEST_USERS["dds_examiner_headers"])
        validate_error(res, "ERR_STALE_APPLICATION_VERSION", expected_status=412)
