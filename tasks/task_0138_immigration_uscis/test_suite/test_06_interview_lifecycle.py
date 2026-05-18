"""Interview lifecycle — PRD §3.6.

Coverage:
- Interview only valid for I-485 (ERR_INTERVIEW_NOT_APPLICABLE).
- scheduled_at >= now() + 14 days (ERR_INTERVIEW_TOO_SOON).
- Reachable from RFE_RESPONDED and from BIOMETRICS_COMPLETED.
- Completion requires scheduled_at <= now() and an outcome from
  {RECOMMEND_APPROVAL, RECOMMEND_DENIAL, CONTINUED}.
- Parent advances to READY_FOR_DECISION on completion.
- Non-I-485 cases use the ready-for-decision endpoint instead.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    INTERVIEW_LEAD_DAYS,
    advance_clock_to,
    api_client,
    assert_interview,
    complete_interview,
    complete_interview_payload,
    issue_rfe,
    re_get_case,
    ready_for_decision,
    respond_rfe,
    schedule_biometrics,
    schedule_interview,
    schedule_interview_payload,
    server_offset_iso,
    setup_biometrics_completed,
    setup_filed_case,
    setup_interview_scheduled,
    setup_rfe_responded,
    validate_error,
    validate_success,
)


# ===========================================================================
# Scheduling
# ===========================================================================
class TestInterviewScheduling:

    def test_interview_only_valid_for_i485(self, api):
        """PRD §3.6: "Scheduling an interview against any other case
        type is rejected with ERR_INTERVIEW_NOT_APPLICABLE."

        Claim: POST /cases/{i130_id}/interview ->
        ERR_INTERVIEW_NOT_APPLICABLE.
        """
        bundle = setup_filed_case(case_type="I-130")
        case = bundle["case"]
        scheduled = server_offset_iso(days=INTERVIEW_LEAD_DAYS + 1)
        resp = api_client.schedule_interview(
            case["id"],
            schedule_interview_payload(
                scheduled_at=scheduled, field_office_code="NYC",
            ),
            {"X-User-ID": "officer-x", "X-User-Role": "Officer",
             "Content-Type": "application/json"},
        )
        validate_error(
            resp, ApiErrorId.ERR_INTERVIEW_NOT_APPLICABLE.value,
        )

    def test_schedule_at_14_days_succeeds(self, api):
        """PRD §3.6: "The scheduled_at must be at least 14 days into
        the future".

        Claim: scheduled_at = now() + 14 days exactly is accepted.
        """
        bundle = setup_rfe_responded(case_type="I-485")
        case = bundle["case"]
        scheduled = server_offset_iso(days=INTERVIEW_LEAD_DAYS)
        resp = api_client.schedule_interview(
            case["id"],
            schedule_interview_payload(
                scheduled_at=scheduled, field_office_code="NYC",
            ),
            {"X-User-ID": "officer-x", "X-User-Role": "Officer",
             "Content-Type": "application/json"},
        )
        data = validate_success(resp, expected_status=201)
        assert_interview(data)
        assert data["status"] == "SCHEDULED"

    def test_schedule_too_soon_rejected(self, api):
        """PRD §3.6: "or the request is rejected with
        ERR_INTERVIEW_TOO_SOON."

        Claim: scheduled_at = now() + 13 days -> ERR_INTERVIEW_TOO_SOON.
        """
        bundle = setup_rfe_responded(case_type="I-485")
        case = bundle["case"]
        scheduled = server_offset_iso(days=INTERVIEW_LEAD_DAYS - 1)
        resp = api_client.schedule_interview(
            case["id"],
            schedule_interview_payload(
                scheduled_at=scheduled, field_office_code="NYC",
            ),
            {"X-User-ID": "officer-x", "X-User-Role": "Officer",
             "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_INTERVIEW_TOO_SOON.value)

    def test_interview_from_biometrics_completed_when_no_rfe(self, api):
        """PRD §3.6: "The interview may be scheduled from two prior
        case states: from RFE_RESPONDED, after the case has cleared an
        RFE; or directly from BIOMETRICS_COMPLETED when no RFE
        currently sits OUTSTANDING."

        Claim: I-485 in BIOMETRICS_COMPLETED with no OUTSTANDING RFE
        can have an interview scheduled.
        """
        bundle = setup_biometrics_completed(case_type="I-485")
        case = bundle["case"]
        assert case["status"] == "BIOMETRICS_COMPLETED"
        interview = schedule_interview(case, days_ahead=15)
        assert interview["status"] == "SCHEDULED"
        parent = re_get_case(case["id"])
        assert parent["status"] == "INTERVIEW_SCHEDULED"


# ===========================================================================
# Completion
# ===========================================================================
class TestInterviewCompletion:

    def test_complete_with_outcome_advances_case(self, api):
        """PRD §3.6: "On completion the interview's status becomes
        COMPLETED, the supplied outcome is recorded, the parent case
        advances to READY_FOR_DECISION".

        Claim: completing an interview after its scheduled_at sets
        status=COMPLETED, persists outcome, and transitions parent to
        READY_FOR_DECISION.
        """
        bundle = setup_interview_scheduled()
        interview = bundle["interview"]
        advance_clock_to(server_offset_iso(days=16))
        completed = complete_interview(
            interview, outcome="RECOMMEND_APPROVAL",
        )
        assert completed["status"] == "COMPLETED"
        assert completed["outcome"] == "RECOMMEND_APPROVAL"
        parent = re_get_case(bundle["case"]["id"])
        assert parent["status"] == "READY_FOR_DECISION"

    def test_invalid_outcome_rejected(self, api):
        """PRD §3.6: "the officer to supply an outcome drawn from
        RECOMMEND_APPROVAL, RECOMMEND_DENIAL, or CONTINUED".

        Claim: unknown outcome value -> ERR_VALIDATION.
        """
        bundle = setup_interview_scheduled()
        interview = bundle["interview"]
        advance_clock_to(server_offset_iso(days=16))
        resp = api_client.complete_interview(
            interview["id"],
            {"outcome": "UNKNOWN_OUTCOME"},
            {"X-User-ID": "officer-x", "X-User-Role": "Officer",
             "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Non-I-485 ready-for-decision
# ===========================================================================
class TestReadyForDecision:

    def test_i130_ready_for_decision_via_endpoint(self, api):
        """PRD §3.6: "For non-I-485 cases — I-130, I-765, and I-131 —
        there is no interview. Once biometrics are complete (and no
        RFE is outstanding), an officer manually advances the case to
        READY_FOR_DECISION through the ready-for-decision capability."

        Claim: an I-130 in FILED can advance to READY_FOR_DECISION via
        POST /cases/{id}/ready-for-decision (I-130 has
        requires_biometrics=false, so it qualifies once filed with no
        outstanding RFE).
        """
        bundle = setup_filed_case(case_type="I-130")
        case = bundle["case"]
        advanced = ready_for_decision(case)
        assert advanced["status"] == "READY_FOR_DECISION"
