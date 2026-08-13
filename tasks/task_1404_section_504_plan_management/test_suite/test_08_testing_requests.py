"""Testing accommodation requests: the 14-day lead-time boundary, the flag
gate, and district-only decision roles (PRD §2.1, §3.7, §4)."""
from test_helpers import (
    ApiErrorId,
    create_testing_request,
    make_coordinator_headers,
    make_director_headers,
    make_teacher_headers,
    setup_active_plan,
    validate_error,
    validate_success,
)


def _active_plan_with_testing_request(api, test_date="2026-08-15T00:00:00Z", test_name="State ELA Grade 8"):
    """ACTIVE plan with a test-applicable accommodation; clock at 2026-08-01;
    one testing request in SUBMITTED."""
    ctx = setup_active_plan(
        clock_initial="2025-12-15T00:00:00Z",
        activate_at="2026-08-01T00:00:00Z",
        applies_to_testing=True,
        include_director=True,
    )
    request = create_testing_request(
        ctx["plan"]["id"], ctx["accommodation"]["id"], ctx["coordinator"]["id"],
        test_date, test_name=test_name,
    )
    return ctx, request


class TestLeadTimeBoundary:
    def test_testing_lead_time_exactly_14_vs_13_days(self, api):
        """PRD §3.7: "Forwarding a request to the district requires it to be
        `SUBMITTED` (otherwise `ERR_TESTING_REQUEST_NOT_SUBMITTED`), requires
        the plan to be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`), and enforces
        lead time: the whole-day count from now to `test_date` must be at least
        14 — exactly 14 days passes, 13 fails with
        `ERR_TESTING_LEAD_TIME_INSUFFICIENT`."
        PRD §2.11: "Durations are measured in whole calendar days: the number of
        days between two instants is the floor of their difference expressed in
        days, so a boundary stated as \"at least 14 days\" passes at exactly 14
        and fails at 13."

        Design: Difficulty/boundary_precision_check/testing_lead_time_exactly_14_vs_13_days
        """
        ctx, req_pass = _active_plan_with_testing_request(api, test_date="2026-08-15T00:00:00Z")
        req_fail = create_testing_request(
            ctx["plan"]["id"], ctx["accommodation"]["id"], ctx["coordinator"]["id"],
            "2026-08-14T00:00:00Z", test_name="State Math Grade 8",
        )
        co_headers = make_coordinator_headers(ctx["coordinator"]["id"])
        forwarded = validate_success(api.forward_testing_request(req_pass["id"], co_headers))
        assert forwarded["request_status"] == "PENDING_DISTRICT_REVIEW", (
            "exactly 14 days of lead time passes the boundary (inclusive)"
        )
        resp = api.forward_testing_request(req_fail["id"], co_headers)
        validate_error(resp, ApiErrorId.ERR_TESTING_LEAD_TIME_INSUFFICIENT)

    def test_testing_lead_time_13_days_rejected_and_state_unchanged(self, api):
        """PRD §3.7: "Forwarding a request to the district requires it to be
        `SUBMITTED` (otherwise `ERR_TESTING_REQUEST_NOT_SUBMITTED`), requires
        the plan to be `ACTIVE` (otherwise `ERR_PLAN_NOT_ACTIVE`), and enforces
        lead time: the whole-day count from now to `test_date` must be at least
        14 — exactly 14 days passes, 13 fails with
        `ERR_TESTING_LEAD_TIME_INSUFFICIENT`."

        Design: Difficulty/boundary_precision_check/testing_lead_time_exactly_14_vs_13_days
        """
        ctx, req_fail = _active_plan_with_testing_request(api, test_date="2026-08-14T00:00:00Z",
                                                          test_name="State Math Grade 8")
        co_headers = make_coordinator_headers(ctx["coordinator"]["id"])
        resp = api.forward_testing_request(req_fail["id"], co_headers)
        validate_error(resp, ApiErrorId.ERR_TESTING_LEAD_TIME_INSUFFICIENT)
        after = validate_success(api.get_testing_request(req_fail["id"], co_headers))
        assert after["request_status"] == "SUBMITTED", (
            "a rejected forward must leave the request in SUBMITTED"
        )


class TestFlagAndDecisionRoles:
    def test_testing_request_flag_conditional_action(self, api):
        """PRD §3.7: "Both are terminal — except that an already-`APPROVED`
        request can later be flagged for state audit: flagging requires
        `APPROVED` (otherwise `ERR_TESTING_REQUEST_NOT_APPROVED`) and is a
        retroactive integrity check permitted only when the `test_name` starts
        with \"State \" and the underlying accommodation has since reached
        `DISCONTINUED`, moving the request to `FLAGGED_FOR_STATE_AUDIT`."

        Design: Corner/endpoints/testing_request_flag_conditional_action
        """
        ctx, request = _active_plan_with_testing_request(api, test_date="2027-01-01T00:00:00Z")
        # The request is still SUBMITTED — flagging requires APPROVED.
        resp = api.flag_testing_request(request["id"], make_director_headers(ctx["director"]["id"]))
        validate_error(resp, ApiErrorId.ERR_TESTING_REQUEST_NOT_APPROVED)

    def test_teacher_cannot_approve_testing_request(self, api):
        """PRD §2.1: "Each operation is restricted to a designated set of roles
        (enumerated per endpoint in §4); an authenticated caller whose role is
        not permitted for the requested operation is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §4: POST `/testing-requests/{requestId}/approve` — "District
        approves testing accommodation" — authorized role: District504Director.

        Design: Corner/roles/teacher_cannot_approve_testing_request
        """
        # Clock is 2026-08-01; the test date is 19 days out, satisfying the
        # 14-day lead time at forwarding.
        ctx, request = _active_plan_with_testing_request(api, test_date="2026-08-20T00:00:00Z",
                                                         test_name="ELA")
        co_headers = make_coordinator_headers(ctx["coordinator"]["id"])
        validate_success(api.forward_testing_request(request["id"], co_headers))
        # The request is now PENDING_DISTRICT_REVIEW; a Teacher may not approve.
        resp = api.approve_testing_request(request["id"], make_teacher_headers(ctx["teacher"]["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
