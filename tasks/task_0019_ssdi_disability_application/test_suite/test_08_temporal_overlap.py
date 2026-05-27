"""Resource temporal-overlap conflicts: reconsideration 60-day appeal
window; hearing 75-day lead-time half-open interval."""
import pytest
from test_helpers import (
    validate_error, validate_success, get_success_data, api_client, TEST_USERS,
    set_clock,
    setup_application_in_medical_review,
    deny_medical_setup,
    setup_hearing_in_requested,
    request_reconsideration, request_hearing,
    schedule_hearing_payload,
    make_claimant_headers,
)


# =========================================================================
# Instance: reconsideration_window_60_day_appeal_period_overlap_with_decision_date
# =========================================================================

class TestReconsiderationWindow60DayAppealPeriodOverlapWithDecisionDate:
    """Reconsideration must be requested within 60 days of the medical
    denial; outside the window the request is rejected."""

    def test_reconsideration_after_62_days_rejected(self, api):
        """PRD §3.5: "Requesting reconsideration is permitted only while
        the application is in `DENIED_MEDICAL` (any other from-state
        yields `ERR_INVALID_APPLICATION_STATE`) and only within sixty days
        of the underlying `MedicalDeterminationDecision`'s `created_at` —
        measured as the current server time being on or before that
        decision's `created_at` plus sixty days. A request that arrives
        after the sixtieth day is rejected with
        `ERR_RECONSIDERATION_WINDOW_EXPIRED` (422)."

        Design: Difficulty/resource_temporal_overlap/reconsideration_window_60_day_appeal_period_overlap_with_decision_date
        """
        set_clock("2026-01-15T00:00:00Z")
        # Decision created_at = 2026-03-15.
        ctx = deny_medical_setup(
            claimant_overrides={
                "ssn_last4": "3333",
                "full_name": "Late Recon",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
            medical_clock_override="2026-03-15T00:00:00Z",
        )
        app_id = ctx["application"]["id"]
        claimant_id = ctx["claimant"]["id"]
        # Move past day 60. decision_date + 60 days = 2026-05-14. Use 2026-05-16.
        set_clock("2026-05-16T00:00:00Z")
        res = api_client.request_reconsideration(app_id, make_claimant_headers(claimant_id))
        validate_error(res, "ERR_RECONSIDERATION_WINDOW_EXPIRED", expected_status=422)

    def test_reconsideration_within_window_succeeds(self, api):
        """PRD §3.5: "Requesting reconsideration is permitted only while
        the application is in `DENIED_MEDICAL` (any other from-state
        yields `ERR_INVALID_APPLICATION_STATE`) and only within sixty days
        of the underlying `MedicalDeterminationDecision`'s `created_at`"
        PRD §3.5: "On a successful request, the application transitions
        from `DENIED_MEDICAL` to `RECONSIDERATION`, its `medical_decision`
        is reset to `PENDING`, and its `version` increments."

        Design: Difficulty/resource_temporal_overlap/reconsideration_window_60_day_appeal_period_overlap_with_decision_date
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = deny_medical_setup(
            claimant_overrides={
                "ssn_last4": "3334",
                "full_name": "On Time Recon",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
            medical_clock_override="2026-03-15T00:00:00Z",
        )
        app_id = ctx["application"]["id"]
        claimant_id = ctx["claimant"]["id"]
        # Stay within the 60-day window; immediate retry succeeds.
        res = api_client.request_reconsideration(app_id, make_claimant_headers(claimant_id))
        data = get_success_data(res)
        assert data["status"] == "RECONSIDERATION"
        assert data["medical_decision"] == "PENDING"


# =========================================================================
# Instance: hearing_lead_time_open_lower_bound_interval_collides
# =========================================================================

class TestHearingLeadTimeOpenLowerBoundIntervalCollides:
    """The hearing-schedule lead-time check is on a different resource
    (HearingRequest, not Application) and uses a half-open interval. The
    boundary is the same 75-day rule; this instance asserts the rejection
    one day below the boundary."""

    def test_scheduled_date_74_days_after_request_rejected(self, api):
        """PRD §3.5: "the supplied `scheduled_date` must be at least 75
        days after the hearing's server-recorded `requested_date` — that
        is, `scheduled_date` is on or after `requested_date` plus 75 days.
        A `scheduled_date` that is earlier than that threshold is rejected
        with `ERR_HEARING_LEAD_TIME` (422)."

        Design: Difficulty/resource_temporal_overlap/hearing_lead_time_open_lower_bound_interval_collides
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_hearing_in_requested(
            claimant_overrides={
                "ssn_last4": "4444",
                "full_name": "Hear Bound",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
        )
        hearing = ctx["hearing"]
        # requested_date = 2026-01-15; 74 days = 2026-03-30 (outside half-open lower bound).
        payload = schedule_hearing_payload("2026-03-30T00:00:00Z")
        res = api_client.schedule_hearing(hearing["id"], payload, TEST_USERS["alj_headers"])
        validate_error(res, "ERR_HEARING_LEAD_TIME", expected_status=422)

    def test_scheduled_date_far_after_75_days_accepted(self, api):
        """PRD §3.5: "On success, the server sets the hearing's `status`
        to `SCHEDULED`, stamps the calling judge's `X-User-ID` into
        `alj_user_id`, persists the supplied `scheduled_date`, and
        increments the hearing's `version`."

        Design: Difficulty/resource_temporal_overlap/hearing_lead_time_open_lower_bound_interval_collides
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_hearing_in_requested(
            claimant_overrides={
                "ssn_last4": "4445",
                "full_name": "Hear Far",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
        )
        hearing = ctx["hearing"]
        # 100 days after requested_date.
        payload = schedule_hearing_payload("2026-04-25T00:00:00Z")
        res = api_client.schedule_hearing(hearing["id"], payload, TEST_USERS["alj_headers"])
        data = validate_success(res, expected_status=200)
        assert data["status"] == "SCHEDULED"
