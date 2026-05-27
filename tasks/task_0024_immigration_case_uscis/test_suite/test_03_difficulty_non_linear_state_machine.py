"""Difficulty Rule 3 — non_linear_state_machine.

Tests for cycles and branches in the Case state machine: the UNDER_REVIEW ↔
RFE_PENDING revision cycle (rfe_round_count persists across the back-edge),
and the three-way INTERVIEW_COMPLETED branching (APPROVE / DENY / REOPEN).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    setup_rfe_pending_i130,
    setup_interview_completed_i485,
    make_applicant_headers,
    rfe_respond_payload,
    decide_case_payload,
)


class TestCaseUnderReviewRfePendingRevisionCycle:
    """Case can cycle UNDER_REVIEW → RFE_PENDING → UNDER_REVIEW.
    On return to UNDER_REVIEW, rfe_round_count is NOT reset."""

    def test_rfe_respond_returns_case_to_under_review_without_resetting_count(self, api):
        """PRD §3.6: "the parent case's status cascades back to UNDER_REVIEW (a back-edge in
        the case lifecycle — and importantly, `rfe_round_count` is not reset)"

        Design: Difficulty/non_linear_state_machine/case_under_review_rfe_pending_under_review_revision_cycle
        """
        applicant, case_rfe, rfe, _officer_headers = setup_rfe_pending_i130()
        # case_rfe is now in RFE_PENDING with rfe_round_count == 1.
        assert case_rfe["status"] == "RFE_PENDING"
        assert case_rfe["rfe_round_count"] == 1

        headers = make_applicant_headers(applicant["id"])
        res = api.respond_to_rfe(
            rfe["id"],
            rfe_respond_payload(case_rfe["version"], "Submitted birth certificate"),
            headers,
        )
        validate_success(res, 200)
        # Re-read case to confirm cascade.
        case_after = get_success_data(api.get_case(case_rfe["id"], headers))
        assert case_after["status"] == "UNDER_REVIEW"
        # rfe_round_count is preserved across the back-edge.
        assert case_after["rfe_round_count"] == 1

    def test_rfe_status_is_responded_after_response(self, api):
        """PRD §3.6: "the RFE's `status` becomes `RESPONDED`, its `responded_at` is stamped
        to `ClockState.current_utc`"

        Design: Difficulty/non_linear_state_machine/case_under_review_rfe_pending_under_review_revision_cycle
        """
        applicant, case_rfe, rfe, _officer_headers = setup_rfe_pending_i130()
        headers = make_applicant_headers(applicant["id"])
        res = api.respond_to_rfe(
            rfe["id"],
            rfe_respond_payload(case_rfe["version"], "Submitted birth certificate"),
            headers,
        )
        validate_success(res, 200)
        rfe_after = get_success_data(api.get_rfe(rfe["id"], headers))
        assert rfe_after["status"] == "RESPONDED"


class TestInterviewCompletedBranchingReopen:
    """From INTERVIEW_COMPLETED the case has three outbound transitions
    (APPROVED, DENIED, UNDER_REVIEW), gated by the latest interview's
    decision_after_interview value and the decide call's `decision`."""

    def test_reopen_branch_when_interview_decision_was_needs_review(self, api):
        """PRD §3.7: "To reopen the case for further adjudication, the latest interview's
        `decision_after_interview` must be `NEEDS_REVIEW`, the supplied `decision`
        must be `REOPEN`, `expected_case_version` must match, and the case's
        `status` cascades back to `UNDER_REVIEW` along a revision back-edge"

        Design: Difficulty/non_linear_state_machine/interview_completed_branching_approve_deny_reopen_fan_join
        """
        applicant, case_ic, interview, officer_headers = setup_interview_completed_i485(
            interview_decision="NEEDS_REVIEW",
            preference_category="F2A",
            country="WORLDWIDE",
            final_action_cutoff="CURRENT",
        )
        assert case_ic["status"] == "INTERVIEW_COMPLETED"

        res = api.decide_case(
            case_ic["id"],
            decide_case_payload("REOPEN", case_ic["version"]),
            officer_headers,
        )
        body = validate_success(res, 200)
        assert body["status"] == "UNDER_REVIEW"
        # The interview's recorded decision is preserved.
        interview_after = get_success_data(api.get_interview(interview["id"],
                                                              officer_headers))
        assert interview_after["decision_after_interview"] == "NEEDS_REVIEW"

    def test_deny_branch_terminates_case_to_denied(self, api):
        """PRD §3.7: "To deny the case, the supplied `decision` must be `DENY`,
        `expected_case_version` must match, and the case's `status` becomes
        the terminal `DENIED`"

        Design: Difficulty/non_linear_state_machine/interview_completed_branching_approve_deny_reopen_fan_join
        """
        applicant, case_ic, _interview, officer_headers = setup_interview_completed_i485(
            interview_decision="DENY",
            preference_category="F2A",
            country="WORLDWIDE",
            final_action_cutoff="CURRENT",
        )
        res = api.decide_case(
            case_ic["id"],
            decide_case_payload("DENY", case_ic["version"]),
            officer_headers,
        )
        body = validate_success(res, 200)
        assert body["status"] == "DENIED"
