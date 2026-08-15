"""Selection-notice answering, notice expiry via the ops checkpoint, and
operator ownership of notices."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    make_operator,
    make_vessel_operator_headers,
    set_clock,
    setup_notice_scenario,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["program_coordinator_headers"]


class TestNoticeAnswering:
    def test_decline_is_terminal(self, api, coordinator_headers):
        """PRD §3.3: "Declining, under the same ownership rule, moves it
        `ISSUED` → `DECLINED`, a terminal state, likewise incrementing
        `version`."

        Design: Corner/state_machines/notice_decline_terminal_and_second_accept_rejected
        """
        bundle = setup_notice_scenario(accept=False)
        notice = bundle["notice"]
        op = make_vessel_operator_headers(bundle["operator"]["id"])

        declined = validate_success(api.decline_selection_notice(notice["id"], {}, op))
        assert declined["status"] == "DECLINED"

        accept_after = api.accept_selection_notice(notice["id"], {}, op)
        validate_error(accept_after, ApiErrorId.ERR_INVALID_STATE, 409)
        decline_again = api.decline_selection_notice(notice["id"], {}, op)
        validate_error(decline_again, ApiErrorId.ERR_INVALID_STATE, 409)

    def test_accept_after_response_deadline_rejected(self, api, coordinator_headers):
        """PRD §3.3: "Accepting requires that the caller own the notice's
        vessel and that the current clock has not passed the
        `response_deadline` — a late answer is rejected with
        `ERR_NOTICE_EXPIRED`"

        Design: Corner/validations/notice_accept_after_response_deadline_rejected
        """
        bundle = setup_notice_scenario(accept=False)
        notice = bundle["notice"]
        # Notice response_deadline is 2026-09-05; move the clock past it.
        set_clock("2026-09-06T00:00:00Z")
        resp = api.accept_selection_notice(
            notice["id"], {}, make_vessel_operator_headers(bundle["operator"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_NOTICE_EXPIRED, 409)
        current = validate_success(api.get_selection_notice(notice["id"], coordinator_headers))
        assert current["status"] == "ISSUED"

    def test_operator_cannot_accept_anothers_notice(self, api, coordinator_headers):
        """PRD §2.1: "When `X-User-Role` is `VesselOperator`, `X-User-ID` is
        the `id` of the acting `VesselOperator`; ownership of vessels is
        decided by comparing a vessel's `operator_id` to `X-User-ID`, and that
        ownership in turn gates the operator's notices, deployments' invoices,
        EM enrollments, EM trips, and harassment-report appeals." PRD §3.3:
        "Accepting requires that the caller own the notice's vessel and that
        the current clock has not passed the `response_deadline` — a late
        answer is rejected with `ERR_NOTICE_EXPIRED`"

        Design: Corner/rbac/operator_cannot_accept_another_operators_notice
        """
        bundle = setup_notice_scenario(accept=False)
        other_operator = make_operator()
        resp = api.accept_selection_notice(
            bundle["notice"]["id"], {},
            make_vessel_operator_headers(other_operator["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        current = validate_success(
            api.get_selection_notice(bundle["notice"]["id"], coordinator_headers)
        )
        assert current["status"] == "ISSUED"


class TestOpsCheckpoint:
    def test_ops_run_expires_lapsed_notices(self, api, coordinator_headers):
        """PRD §2.7: "First, every selection notice still `ISSUED` whose
        `response_deadline` lies in the past is moved to `EXPIRED`." and "The
        response tallies the sweep's work in five counters:
        `expired_notice_count`, `overdue_invoice_count`,
        `delinquent_operator_count`, `suspended_vessel_count`, and
        `cancelled_deployment_count`."

        Design: Corner/validations/ops_run_expires_issued_notice_past_deadline
        """
        bundle = setup_notice_scenario(accept=False)
        set_clock("2026-09-06T00:00:00Z")
        result = validate_success(api.ops_run({}, ADMIN))
        assert result["expired_notice_count"] == 1
        current = validate_success(
            api.get_selection_notice(bundle["notice"]["id"], coordinator_headers)
        )
        assert current["status"] == "EXPIRED"
