"""Appeals: ruling state guard, the inclusive filing window, and hearing
segregation of duties (PRD §2.8, §3.9)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, CLOCK,
    create_denied_application, file_application_denial_appeal,
    schedule_appeal_hearing, set_clock,
    make_staff_headers, make_appeals_officer_headers,
    make_applicant_headers, api_client,
)

STAFF = make_staff_headers("staff_1")


def _appeal_context(school_name, applicant_id, reviewer_id, panelist_id,
                    interview_start, interview_end, denial_reason, grounds):
    """Denied application with a FILED appeal from its applicant."""
    app = create_denied_application(school_name=school_name,
                                    applicant_id=applicant_id,
                                    reviewer_id=reviewer_id,
                                    panelist_id=panelist_id,
                                    denial_reason=denial_reason,
                                    interview_start=interview_start,
                                    interview_end=interview_end)
    appeal = file_application_denial_appeal(app["id"], applicant_id, grounds)
    return app, appeal


class TestAppealRuleBeforeScheduleRejected:
    def test_rule_on_filed_appeal_rejected(self, api):
        """PRD §3.9: "Ruling belongs to the assigned `AppealsOfficer` alone:
        the caller's `X-User-ID` must equal `hearing_officer_user_id`
        (`ERR_APPEAL_OFFICER_MISMATCH`), and the appeal must be
        `HEARING_SCHEDULED` (`ERR_APPEAL_INVALID_STATE`)."

        Design: Corner/state_machines/sm_appeal_rule_before_schedule_rejected
        """
        _app, appeal = _appeal_context(
            "SM Appeal Academy", "applicant_s14", "rev_s14", "rev_panel_s14",
            "2026-06-05T13:00:00Z", "2026-06-05T14:00:00Z",
            "Facility plan not credible", "Interview conducted unfairly")
        assert appeal["status"] == "FILED"
        res = api.rule_appeal(appeal["id"], {"ruling": "UPHELD"},
                              make_appeals_officer_headers("officer_s14"))
        validate_error(res, ApiErrorId.ERR_APPEAL_INVALID_STATE, expected_status=409)
        current = validate_success(api.get_appeal(appeal["id"], STAFF), 200)
        assert current["status"] == "FILED"
        assert current["ruling"] is None


class TestAppealWindowInclusive30Days:
    def test_filing_at_exactly_30_days_succeeds_one_second_later_fails(self, api):
        """PRD §3.9: "And the window is finite: `filed_at` must fall at or
        before thirty days after the target's decision instant — the window is
        inclusive of the final day — else `ERR_APPEAL_WINDOW_EXPIRED`."

        Design: Corner/validations/val_appeal_window_inclusive_30_days
        """
        # Both applications are DENIED at the default clock 2026-05-01T00:00:00Z.
        app_a = create_denied_application(
            school_name="Val Window Academy A", applicant_id="applicant_v6",
            reviewer_id="rev_v6", panelist_id="rev_panel_v6",
            denial_reason="Budget unrealistic",
            interview_start="2026-06-16T10:00:00Z",
            interview_end="2026-06-16T11:00:00Z")
        app_b = create_denied_application(
            school_name="Val Window Academy B", applicant_id="applicant_v6",
            reviewer_id="rev_v6", panelist_id="rev_panel_v6b",
            denial_reason="Facility not secured",
            interview_start="2026-06-16T12:00:00Z",
            interview_end="2026-06-16T13:00:00Z")

        set_clock(CLOCK["DEFAULT_PLUS_30D"])
        filed = validate_success(
            api.file_appeal({"target_type": "APPLICATION_DENIAL",
                             "target_id": app_a["id"], "grounds": "Within window"},
                            make_applicant_headers("applicant_v6")), 201)
        assert filed["status"] == "FILED"
        assert filed["school_id"] is None

        set_clock(CLOCK["DEFAULT_PLUS_30D_1S"])
        res = api.file_appeal({"target_type": "APPLICATION_DENIAL",
                               "target_id": app_b["id"], "grounds": "One second late"},
                              make_applicant_headers("applicant_v6"))
        validate_error(res, ApiErrorId.ERR_APPEAL_WINDOW_EXPIRED, expected_status=422)


class TestAppealHearingSegregationOfDuties:
    def test_decider_cannot_be_hearing_officer_then_valid_officer_succeeds(self, api):
        """PRD §2.8: "The hearing officer assigned to an appeal must not be the
        original decider of the contested target, else
        `ERR_SOD_APPEAL_DECIDER_CONFLICT` (HTTP 403); and the ruling itself may
        only be entered by the assigned officer, else
        `ERR_APPEAL_OFFICER_MISMATCH` (HTTP 403)."
        PRD §3.9: "Scheduling moves the appeal `FILED` → `HEARING_SCHEDULED`
        and records the officer."

        Design: Corner/rbac/rbac_sod_appeal_decider_conflict
        """
        _app, appeal = _appeal_context(
            "RBAC SOD Academy", "applicant_b3", "rev_b3", "rev_panel_b3",
            "2026-06-21T10:00:00Z", "2026-06-21T11:00:00Z",
            "Weak finance plan", "Finance evidence overlooked")
        res = api.schedule_hearing(appeal["id"],
                                   {"hearing_officer_user_id": "board_1"}, STAFF)
        validate_error(res, ApiErrorId.ERR_SOD_APPEAL_DECIDER_CONFLICT,
                       expected_status=403)
        scheduled = validate_success(
            api.schedule_hearing(appeal["id"],
                                 {"hearing_officer_user_id": "officer_b3"}, STAFF), 200)
        assert scheduled["status"] == "HEARING_SCHEDULED"
        assert scheduled["hearing_officer_user_id"] == "officer_b3"

    def test_only_assigned_officer_may_rule(self, api):
        """PRD §3.9: "Ruling belongs to the assigned `AppealsOfficer` alone:
        the caller's `X-User-ID` must equal `hearing_officer_user_id`
        (`ERR_APPEAL_OFFICER_MISMATCH`), and the appeal must be
        `HEARING_SCHEDULED` (`ERR_APPEAL_INVALID_STATE`)."

        Design: Corner/rbac/rbac_appeal_officer_mismatch
        """
        _app, appeal = _appeal_context(
            "RBAC Officer Academy", "applicant_b4", "rev_b4", "rev_panel_b4",
            "2026-06-22T10:00:00Z", "2026-06-22T11:00:00Z",
            "Enrollment plan thin", "Enrollment data was attached")
        schedule_appeal_hearing(appeal["id"], "officer_b4")
        res = api.rule_appeal(appeal["id"], {"ruling": "UPHELD"},
                              make_appeals_officer_headers("officer_WRONG_b4"))
        validate_error(res, ApiErrorId.ERR_APPEAL_OFFICER_MISMATCH, expected_status=403)
        current = validate_success(api.get_appeal(appeal["id"], STAFF), 200)
        assert current["status"] == "HEARING_SCHEDULED"
        assert current["ruling"] is None
