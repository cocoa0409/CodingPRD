"""Medical evidence, application drafting, and submit-time gates.

Covers PRD §3.3 (evidence lifecycle + submit) and the QC and evidence
boundary tests called out in the difficulty index (rule 6).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_evidence,
    add_listing_evidence,
    add_quarter_credit,
    api_client,
    assert_medical_evidence,
    create_claimant,
    create_draft_application,
    create_listing_match_evidence_payload,
    create_rfc_assessment_evidence_payload,
    date_to_iso,
    make_claimant_headers,
    reject_evidence,
    seed_qcs_for_insured_status,
    setup_application_at_initial_review,
    setup_claimant_with_qcs_for_recent_window,
    setup_insured_claimant,
    submit_application,
    utcnow,
    validate_error,
    validate_success,
)


class TestMedicalEvidenceLifecycle:

    def test_listing_match_evidence_arrives_submitted(self, api):
        """PRD §3.3: "A newly submitted row arrives in status
        SUBMITTED."
        """
        claimant = create_claimant()
        resp = api.create_medical_evidence(
            claimant["id"],
            create_listing_match_evidence_payload(
                evidence_date=claimant["alleged_onset_date"],
            ),
            make_claimant_headers(claimant["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert_medical_evidence(data)
        assert data["status"] == "SUBMITTED"
        assert data["source_type"] == "LISTING_MATCH"
        assert data["listing_code"] == "1.15"

    def test_dds_examiner_accepts_submitted_evidence(self, api):
        """PRD §3.3: "A DDS examiner reviews it and either accepts it,
        transitioning SUBMITTED to ACCEPTED, or rejects it,
        transitioning SUBMITTED to REJECTED."
        """
        claimant = create_claimant()
        ev = add_listing_evidence(
            claimant["id"],
            evidence_date=claimant["alleged_onset_date"],
        )
        accepted = accept_evidence(claimant["id"], ev["id"])
        assert accepted["status"] == "ACCEPTED"

    def test_dds_examiner_rejects_submitted_evidence(self, api):
        """PRD §3.3: "A DDS examiner reviews it and either accepts it,
        transitioning SUBMITTED to ACCEPTED, or rejects it,
        transitioning SUBMITTED to REJECTED."
        """
        claimant = create_claimant()
        ev = add_listing_evidence(
            claimant["id"],
            evidence_date=claimant["alleged_onset_date"],
        )
        rejected = reject_evidence(claimant["id"], ev["id"])
        assert rejected["status"] == "REJECTED"


class TestApplicationSubmission:

    def test_submit_advances_draft_to_initial_review(self, api):
        """PRD §3.3: "Submitting the draft advances the application
        from DRAFT to INITIAL_REVIEW after three preconditions are
        evaluated in this order".
        """
        claimant, application, _ = setup_application_at_initial_review()
        assert application["status"] == "INITIAL_REVIEW"

    def test_submit_without_insured_status_returns_qc_insufficient(self, api):
        """PRD §3.3: "the claimant's insured_status must be INSURED
        (otherwise ERR_QC_INSUFFICIENT at 422)".
        """
        # Create a claimant with zero QCs so insured_status remains
        # NOT_INSURED.
        claimant = setup_insured_claimant(total_qcs=0, seed_qcs=False)
        # Submit accepted evidence so the OTHER gate is clear.
        ev = add_listing_evidence(
            claimant["id"], evidence_date=claimant["alleged_onset_date"],
        )
        accept_evidence(claimant["id"], ev["id"])
        application = create_draft_application(claimant["id"])
        resp = api.submit_application(
            claimant["id"], application["id"],
            make_claimant_headers(claimant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_QC_INSUFFICIENT.value)

    def test_submit_without_accepted_evidence_returns_evidence_insufficient(
        self, api,
    ):
        """PRD §3.3: "at least one MedicalEvidence row for the claimant
        must have status ACCEPTED (otherwise ERR_EVIDENCE_INSUFFICIENT
        at 422)".
        """
        claimant = setup_insured_claimant()
        # No evidence at all.
        application = create_draft_application(claimant["id"])
        resp = api.submit_application(
            claimant["id"], application["id"],
            make_claimant_headers(claimant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EVIDENCE_INSUFFICIENT.value)


class TestQCRecentWindowBoundary:
    """Difficulty design rule 6: qc_recent_window_boundary_on_submit."""

    def test_qc_recent_window_at_boundary_accepts_submit(self, api):
        """# difficulty: boundary_precision_check/qc_recent_window_boundary_on_submit

        PRD §3.2: "If the age is 31 or older, twenty QCs are required
        within a forty-quarter window ending at alleged_onset_date."
        PRD §3.2: "insured_status is INSURED if and only if
        total_qc_earned is at least qc_required and qc_recent_window
        is at least qc_recent_required; otherwise it is NOT_INSURED."

        Claim: at exactly 20 recent QCs (the >= 20 threshold), submit
        succeeds and the application advances to INITIAL_REVIEW.
        """
        aod = date(2024, 4, 15)
        dob = date(1989, 4, 15)  # age 35 at AOD -> qc_recent_required = 20
        claimant = setup_claimant_with_qcs_for_recent_window(
            qc_count_in_recent_window=20, aod=aod, dob=dob,
        )
        assert claimant["qc_recent_required"] == 20
        assert claimant["qc_recent_window"] == 20
        assert claimant["insured_status"] == "INSURED"
        ev = add_listing_evidence(
            claimant["id"], evidence_date=date_to_iso(aod),
        )
        accept_evidence(claimant["id"], ev["id"])
        application = create_draft_application(claimant["id"])
        resp = api.submit_application(
            claimant["id"], application["id"],
            make_claimant_headers(claimant["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "INITIAL_REVIEW"

    def test_qc_recent_window_below_boundary_rejects_submit(self, api):
        """# difficulty: boundary_precision_check/qc_recent_window_boundary_on_submit

        PRD §3.2: "If the age is 31 or older, twenty QCs are required
        within a forty-quarter window ending at alleged_onset_date."
        PRD §3.3: "the claimant's insured_status must be INSURED
        (otherwise ERR_QC_INSUFFICIENT at 422)".

        Boundary claim: at 19 recent QCs (just below the 20 threshold),
        the recent-work test fails and submit yields
        ERR_QC_INSUFFICIENT.
        """
        aod = date(2024, 4, 15)
        dob = date(1989, 4, 15)
        claimant = setup_claimant_with_qcs_for_recent_window(
            qc_count_in_recent_window=19, aod=aod, dob=dob,
        )
        assert claimant["qc_recent_required"] == 20
        ev = add_listing_evidence(
            claimant["id"], evidence_date=date_to_iso(aod),
        )
        accept_evidence(claimant["id"], ev["id"])
        application = create_draft_application(claimant["id"])
        resp = api.submit_application(
            claimant["id"], application["id"],
            make_claimant_headers(claimant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_QC_INSUFFICIENT.value)


class TestEmptyEvidenceBoundary:
    """Difficulty design rule 6: empty_collection_no_accepted_evidence_on_submit."""

    def test_zero_accepted_evidence_rejects_submit(self, api):
        """# difficulty: boundary_precision_check/empty_collection_no_accepted_evidence_on_submit

        PRD §3.3: "at least one MedicalEvidence row for the claimant
        must have status ACCEPTED (otherwise ERR_EVIDENCE_INSUFFICIENT
        at 422)".

        Empty-collection boundary: count of ACCEPTED evidence == 0.
        """
        claimant = setup_insured_claimant()
        # Submit evidence but explicitly REJECT it.
        ev = add_listing_evidence(
            claimant["id"], evidence_date=claimant["alleged_onset_date"],
        )
        reject_evidence(claimant["id"], ev["id"])
        application = create_draft_application(claimant["id"])
        resp = api.submit_application(
            claimant["id"], application["id"],
            make_claimant_headers(claimant["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EVIDENCE_INSUFFICIENT.value)

    def test_one_accepted_evidence_crosses_boundary(self, api):
        """# difficulty: boundary_precision_check/empty_collection_no_accepted_evidence_on_submit

        PRD §3.3: "at least one MedicalEvidence row for the claimant
        must have status ACCEPTED (otherwise ERR_EVIDENCE_INSUFFICIENT
        at 422)".

        Boundary crossed: exactly 1 ACCEPTED evidence row clears the
        gate.
        """
        claimant = setup_insured_claimant()
        # First reject one to establish 0.
        ev1 = add_listing_evidence(
            claimant["id"], evidence_date=claimant["alleged_onset_date"],
        )
        reject_evidence(claimant["id"], ev1["id"])
        # Then submit a second one and ACCEPT it -> exactly 1 ACCEPTED.
        ev2 = add_listing_evidence(
            claimant["id"], evidence_date=claimant["alleged_onset_date"],
        )
        accept_evidence(claimant["id"], ev2["id"])
        application = create_draft_application(claimant["id"])
        resp = api.submit_application(
            claimant["id"], application["id"],
            make_claimant_headers(claimant["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "INITIAL_REVIEW"
