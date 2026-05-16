"""Initial review: start-review, request-info, resume-review.

PRD §3.4 (review thresholds at 0.50 / 0.75), §2.8 (validation
priority).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    EVIDENCE_THRESHOLD_RESUME_REVIEW,
    EVIDENCE_THRESHOLD_START_REVIEW,
    TEST_DEFAULTS,
    TEST_USERS,
    attach_categories,
    create_authorization_request,
    make_provider_headers,
    occ_payload,
    re_get_authorization,
    request_info,
    resume_review,
    setup_reference_data,
    setup_submitted_authorization,
    setup_under_review_authorization,
    start_review,
    submit_authorization,
    validate_error,
    validate_success,
)


# ===========================================================================
# Start-review and the 0.50 threshold
# ===========================================================================
class TestStartReview:
    """PRD §3.4: SUBMITTED → UNDER_REVIEW gated by 0.50."""

    def test_start_review_transitions_to_under_review(self, api):
        """PRD §3.4: "Once an authorization is SUBMITTED, the payer's
        InitialReviewer may begin a clinical review by starting it,
        advancing the authorization from SUBMITTED to UNDER_REVIEW."

        Claim: start-review on SUBMITTED with sufficient evidence ->
        status=UNDER_REVIEW.
        """
        _, _, _, auth, _ = setup_under_review_authorization()
        assert auth["status"] == "UNDER_REVIEW"

    def test_start_review_below_threshold_rejected(self, api):
        """PRD §3.4: "the request's evidence_completeness_score must be
        at least 0.50. A request that does not yet meet that bar is
        rejected with ERR_EVIDENCE_INSUFFICIENT."

        Claim: submitted with only 1 of 4 required categories (score
        0.25) → start-review returns ERR_EVIDENCE_INSUFFICIENT.
        """
        cats = list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"])
        _, _, _, auth, _ = setup_submitted_authorization(
            required_evidence_categories=cats,
            evidence_categories_to_attach=cats[:1],  # 1/4 -> 0.25
        )
        res = api.start_review(
            auth["id"], occ_payload(version=auth["version"]),
            TEST_USERS["initial_reviewer_headers"],
        )
        validate_error(res, "ERR_EVIDENCE_INSUFFICIENT")

    def test_start_review_score_exactly_half_succeeds(self, api):
        """PRD §3.4: "the request's evidence_completeness_score must be
        at least 0.50."

        Claim: a submitted authorization with score exactly 0.50 (2 of
        4 required) → start-review succeeds. (boundary precision: '>=')

        Difficulty: boundary_precision_check/evidence_completeness_at_exact_0_50_threshold
        """
        # difficulty: boundary_precision_check/evidence_completeness_at_exact_0_50_threshold
        cats = list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"])
        _, _, _, auth, _ = setup_submitted_authorization(
            required_evidence_categories=cats,
            evidence_categories_to_attach=cats[:2],  # 2/4 -> 0.50
        )
        assert auth["evidence_completeness_score"] == 0.50
        res = api.start_review(
            auth["id"], occ_payload(version=auth["version"]),
            TEST_USERS["initial_reviewer_headers"],
        )
        updated = validate_success(res, 200)
        assert updated["status"] == "UNDER_REVIEW"


# ===========================================================================
# Request-info: UNDER_REVIEW → PENDING_INFO
# ===========================================================================
class TestRequestInfo:
    """PRD §3.4: UNDER_REVIEW → PENDING_INFO has no evidence
    precondition."""

    def test_request_info_no_evidence_precondition(self, api):
        """PRD §3.4: "the InitialReviewer may decide that more
        information is required and request information, moving the
        authorization from UNDER_REVIEW to PENDING_INFO. This transition
        has no preconditions on the evidence score; it is the mechanism
        by which the reviewer signals the provider that more evidence
        is needed."

        Claim: request-info on UNDER_REVIEW transitions to PENDING_INFO
        regardless of evidence score.
        """
        _, _, _, auth, _ = setup_under_review_authorization()
        res = api.request_info(
            auth["id"], occ_payload(version=auth["version"]),
            TEST_USERS["initial_reviewer_headers"],
        )
        updated = validate_success(res, 200)
        assert updated["status"] == "PENDING_INFO"


# ===========================================================================
# Resume-review and the 0.75 threshold
# ===========================================================================
class TestResumeReview:
    """PRD §3.4: PENDING_INFO → UNDER_REVIEW gated by 0.75."""

    def test_resume_review_with_full_evidence_succeeds(self, api):
        """PRD §3.4: "The first threshold (0.50) governs the initial
        entry into review; the second (0.75) governs resumption after a
        pending-information cycle."

        Claim: resume-review on a PENDING_INFO request whose evidence
        is at 1.00 → status=UNDER_REVIEW.
        """
        _, _, _, auth, _ = setup_under_review_authorization()
        request_info(authorization=auth)
        auth = re_get_authorization(auth["id"])
        assert auth["status"] == "PENDING_INFO"
        res = api.resume_review(
            auth["id"], occ_payload(version=auth["version"]),
            TEST_USERS["initial_reviewer_headers"],
        )
        updated = validate_success(res, 200)
        assert updated["status"] == "UNDER_REVIEW"

    def test_resume_review_below_threshold_rejected(self, api):
        """PRD §3.4: "Resumption is gated by a stricter evidence
        threshold: evidence_completeness_score must be at least 0.75
        (else ERR_EVIDENCE_INSUFFICIENT)."

        Claim: a PENDING_INFO request with score 0.50 (2/4 required)
        → resume-review returns ERR_EVIDENCE_INSUFFICIENT.
        """
        cats = list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"])
        _, _, _, auth, _ = setup_under_review_authorization(
            required_evidence_categories=cats,
            evidence_categories_to_attach=cats[:2],  # 2/4 -> 0.50
        )
        # Note: start-review needed evidence >= 0.50; we attached
        # exactly 2 cats and started review. Now move to PENDING_INFO
        # and try to resume without raising the score above 0.50.
        request_info(authorization=auth)
        auth = re_get_authorization(auth["id"])
        res = api.resume_review(
            auth["id"], occ_payload(version=auth["version"]),
            TEST_USERS["initial_reviewer_headers"],
        )
        validate_error(res, "ERR_EVIDENCE_INSUFFICIENT")

    def test_resume_review_score_exactly_075_succeeds(self, api):
        """PRD §3.4: "Resumption is gated by a stricter evidence
        threshold: evidence_completeness_score must be at least 0.75".

        Claim: 3 of 4 required categories yields score 0.75 and
        resume-review succeeds. (boundary precision: '>=' at exactly
        0.75)
        """
        cats = list(TEST_DEFAULTS["REQUIRED_EVIDENCE_CATEGORIES"])
        _, _, _, auth, _ = setup_under_review_authorization(
            required_evidence_categories=cats,
            evidence_categories_to_attach=cats[:3],  # 3/4 -> 0.75
        )
        request_info(authorization=auth)
        auth = re_get_authorization(auth["id"])
        assert auth["status"] == "PENDING_INFO"
        # Score should be 0.75 (no p2p bonus, no reuse discount).
        assert auth["evidence_completeness_score"] == 0.75
        res = api.resume_review(
            auth["id"], occ_payload(version=auth["version"]),
            TEST_USERS["initial_reviewer_headers"],
        )
        updated = validate_success(res, 200)
        assert updated["status"] == "UNDER_REVIEW"


# ===========================================================================
# State-machine guards
# ===========================================================================
class TestStateMachineGuards:
    """PRD §2.8: state precondition is priority 5; ERR_INVALID_STATE."""

    def test_start_review_on_draft_rejected(self, api):
        """PRD §2.8: "The target resource is in a state from which the
        requested transition is legal — failure yields
        ERR_INVALID_STATE."

        Claim: start-review on a DRAFT request returns
        ERR_INVALID_STATE.

        Difficulty: priority_pair_validation_conflict/state_vs_business_constraint_evidence_on_submitted
        """
        # difficulty: priority_pair_validation_conflict/state_vs_business_constraint_evidence_on_submitted
        patient, provider, catalog_item = setup_reference_data()
        auth = create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
        )  # DRAFT, no evidence attached -> score 0
        res = api.start_review(
            auth["id"], occ_payload(version=auth["version"]),
            TEST_USERS["initial_reviewer_headers"],
        )
        # Both state (priority 5) and evidence-insufficient (priority
        # 10) would fail; PRD §2.8 names state as the lower priority
        # number → it wins.
        validate_error(res, "ERR_INVALID_STATE")

    def test_resume_review_on_under_review_rejected(self, api):
        """PRD §2.8: "The target resource is in a state from which the
        requested transition is legal — failure yields
        ERR_INVALID_STATE."

        Claim: resume-review on an UNDER_REVIEW request returns
        ERR_INVALID_STATE (already in target state).
        """
        _, _, _, auth, _ = setup_under_review_authorization()
        res = api.resume_review(
            auth["id"], occ_payload(version=auth["version"]),
            TEST_USERS["initial_reviewer_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")
