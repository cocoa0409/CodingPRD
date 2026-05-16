"""Eligibility evaluation lifecycle — PRD §3.2.

Covers: create → request-consent → parent approves → IN_PROGRESS →
finalize (ELIGIBLE / INELIGIBLE), and segregation of duties.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    DISABILITY_CATEGORIES,
    assert_evaluation,
    create_district,
    create_evaluation,
    create_evaluation_payload,
    create_student,
    finalize_evaluation,
    finalize_evaluation_payload,
    find_pending_consent_for_evaluation,
    get_evaluation,
    get_student,
    make_psychologist_headers,
    parent_approve_consent,
    request_evaluation_consent,
    setup_eligible_student,
    validate_error,
    validate_success,
)


class TestEvaluationCreate:
    """PRD §3.2 evaluation creation."""

    def test_create_evaluation_starts_in_requested(
        self, api, psychologist_headers,
    ):
        """PRD §3.2: "starts the evaluation in REQUESTED".

        Claim: a freshly created evaluation has status REQUESTED.
        """
        district = create_district()
        student = create_student(district["id"])
        res = api.create_eligibility_evaluation(
            district["id"], student["id"],
            create_evaluation_payload(evaluation_type="INITIAL"),
            psychologist_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_evaluation(data)
        assert data["status"] == "REQUESTED"
        assert data["evaluation_type"] == "INITIAL"

    def test_evaluation_is_reevaluation_true_only_for_triennial(
        self, api, psychologist_headers,
    ):
        """PRD §3.2: "derives is_reevaluation as true exactly when
        evaluation_type equals TRIENNIAL".

        Claim: TRIENNIAL → is_reevaluation==true; INITIAL and INTERIM
        → false.
        """
        district = create_district()
        student = create_student(district["id"])
        for et, expected in [
            ("INITIAL", False),
            ("TRIENNIAL", True),
            ("INTERIM", False),
        ]:
            e = create_evaluation(
                district["id"], student["id"],
                evaluation_type=et,
                psychologist_headers=psychologist_headers,
            )
            assert e["is_reevaluation"] is expected, (
                f"evaluation_type={et}: expected "
                f"is_reevaluation={expected}, got {e['is_reevaluation']}"
            )


class TestRequestConsentTransition:
    """PRD §3.2 REQUESTED → CONSENT_PENDING."""

    def test_request_consent_moves_to_consent_pending_and_creates_consent(
        self, api, psychologist_headers,
    ):
        """PRD §3.2: "the psychologist transitions the evaluation by
        requesting consent: this moves the evaluation to
        CONSENT_PENDING and simultaneously creates a ParentalConsent
        with scope=EVALUATION, target_resource_type=EligibilityEvaluation,
        target_resource_id equal to the evaluation's id, and
        status=PENDING."

        Claim: post request-consent → evaluation in CONSENT_PENDING
        AND a PENDING EVALUATION consent exists targeting this
        evaluation.
        """
        district = create_district()
        student = create_student(district["id"])
        evaluation = create_evaluation(
            district["id"], student["id"],
            psychologist_headers=psychologist_headers,
        )
        data = validate_success(
            api.request_evaluation_consent(
                district["id"], student["id"], evaluation["id"],
                psychologist_headers,
            ),
        )
        assert data["status"] == "CONSENT_PENDING"
        consent = find_pending_consent_for_evaluation(
            district["id"], student["id"], evaluation["id"],
        )
        assert consent["scope"] == "EVALUATION"
        assert consent["target_resource_type"] == "EligibilityEvaluation"
        assert consent["target_resource_id"] == evaluation["id"]
        assert consent["status"] == "PENDING"

    def test_request_consent_on_non_requested_evaluation_rejected(
        self, api, psychologist_headers,
    ):
        """PRD §3.2: "Attempts to request consent on an evaluation
        not in REQUESTED are rejected with
        ERR_EVALUATION_NOT_REQUESTED."

        Claim: calling request-consent twice fails the second time
        because the evaluation is now CONSENT_PENDING.
        """
        district = create_district()
        student = create_student(district["id"])
        evaluation = create_evaluation(
            district["id"], student["id"],
            psychologist_headers=psychologist_headers,
        )
        # First call succeeds.
        request_evaluation_consent(
            district["id"], student["id"], evaluation["id"],
            psychologist_headers=psychologist_headers,
        )
        # Second call: evaluation is now CONSENT_PENDING, not REQUESTED.
        res = api.request_evaluation_consent(
            district["id"], student["id"], evaluation["id"],
            psychologist_headers,
        )
        validate_error(res, "ERR_EVALUATION_NOT_REQUESTED")


class TestEvaluationApprovalTransitionsToInProgress:
    """PRD §3.2 CONSENT_PENDING → IN_PROGRESS via Parent approve."""

    def test_parent_approve_eval_consent_moves_eval_to_in_progress(
        self, api, psychologist_headers,
    ):
        """PRD §3.2: "because the scope is EVALUATION, automatically
        advances the gated evaluation to IN_PROGRESS and records
        consent_received_at on the evaluation equal to the consent's
        decided_at."

        Claim: parent approval of an EVALUATION consent flips the
        gated evaluation to IN_PROGRESS.
        """
        district = create_district()
        student = create_student(district["id"])
        parent_user_id = student["parent_user_id"]
        evaluation = create_evaluation(
            district["id"], student["id"],
            psychologist_headers=psychologist_headers,
        )
        evaluation = request_evaluation_consent(
            district["id"], student["id"], evaluation["id"],
            psychologist_headers=psychologist_headers,
        )
        consent = find_pending_consent_for_evaluation(
            district["id"], student["id"], evaluation["id"],
        )
        parent_approve_consent(
            district["id"], student["id"], consent["id"],
            parent_user_id=parent_user_id,
        )
        e_now = get_evaluation(
            district["id"], student["id"], evaluation["id"],
        )
        assert e_now["status"] == "IN_PROGRESS"
        assert e_now.get("consent_received_at") is not None


class TestEvaluationFinalize:
    """PRD §3.2 finalize ELIGIBLE / INELIGIBLE."""

    def test_finalize_eligible_branch(
        self, api, psychologist_headers,
    ):
        """PRD §3.2: "A non-empty disability_categories array drives
        the evaluation to ELIGIBLE".

        Claim: finalize with non-empty categories → ELIGIBLE; sets
        finalized_at and Student.current_eligibility_evaluation_id;
        Student.triennial_status becomes ON_TRACK.
        """
        district, student, evaluation = setup_eligible_student(
            disability_categories=["SLD", "OHI"],
        )
        # Reload evaluation and student.
        e_now = get_evaluation(
            district["id"], student["id"], evaluation["id"],
        )
        assert e_now["status"] == "ELIGIBLE"
        assert e_now.get("finalized_at") is not None
        assert e_now["disability_categories"] == ["SLD", "OHI"]
        s_now = get_student(district["id"], student["id"])
        assert s_now["current_eligibility_evaluation_id"] == e_now["id"]
        assert s_now["triennial_status"] == "ON_TRACK"
        assert s_now.get("triennial_reevaluation_due_date") is not None

    def test_finalize_ineligible_branch(
        self, api, psychologist_headers,
    ):
        """PRD §3.2: "an empty array drives it to INELIGIBLE".

        Claim: finalize with empty categories → INELIGIBLE.
        """
        district, student, evaluation = setup_eligible_student(
            disability_categories=[],
        )
        e_now = get_evaluation(
            district["id"], student["id"], evaluation["id"],
        )
        assert e_now["status"] == "INELIGIBLE"
        assert e_now.get("finalized_at") is not None

    def test_finalize_segregation_of_duties_violation(
        self, api, psychologist_headers,
    ):
        """PRD §3.2: "the acting psychologist not also be the
        student's parent_user_id (else
        ERR_SEGREGATION_OF_DUTIES_VIOLATION)".

        Claim: when the X-User-ID of the finalizing psychologist
        equals the student's parent_user_id, finalize is rejected.
        """
        district = create_district()
        # Set parent_user_id to a value, then act as the
        # psychologist with the SAME id — this triggers segregation
        # of duties.
        shared_id = "person-1"
        student = create_student(
            district["id"], parent_user_id=shared_id,
        )
        # Psychologist with the shared id creates the evaluation.
        psych_h = make_psychologist_headers(shared_id)
        e = create_evaluation(
            district["id"], student["id"],
            psychologist_headers=psych_h,
        )
        e = request_evaluation_consent(
            district["id"], student["id"], e["id"],
            psychologist_headers=psych_h,
        )
        consent = find_pending_consent_for_evaluation(
            district["id"], student["id"], e["id"],
        )
        parent_approve_consent(
            district["id"], student["id"], consent["id"],
            parent_user_id=shared_id,
        )
        # Now try to finalize as the SAME shared_id (psychologist).
        res = api.finalize_evaluation(
            district["id"], student["id"], e["id"],
            finalize_evaluation_payload(disability_categories=["SLD"]),
            psych_h,
        )
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES_VIOLATION")

    def test_finalize_on_non_in_progress_evaluation_rejected(
        self, api, psychologist_headers,
    ):
        """PRD §3.2: "IN_PROGRESS → ELIGIBLE requires that the
        evaluation be in IN_PROGRESS (else
        ERR_EVALUATION_NOT_IN_PROGRESS)".

        Claim: attempting to finalize an evaluation still in
        REQUESTED status fails.
        """
        district = create_district()
        student = create_student(district["id"])
        e = create_evaluation(
            district["id"], student["id"],
            psychologist_headers=psychologist_headers,
        )
        # e is in REQUESTED, never moved to IN_PROGRESS.
        res = api.finalize_evaluation(
            district["id"], student["id"], e["id"],
            finalize_evaluation_payload(disability_categories=["SLD"]),
            psychologist_headers,
        )
        validate_error(res, "ERR_EVALUATION_NOT_IN_PROGRESS")
