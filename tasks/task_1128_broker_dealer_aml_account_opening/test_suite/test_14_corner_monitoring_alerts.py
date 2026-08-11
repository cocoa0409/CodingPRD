"""Corner queue: monitoring scans, alert triage, escalation handle, rule RBAC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    approve_account,
    create_account,
    create_customer,
    create_rep,
    create_rule,
    escalate_alert,
    get_account,
    post_structuring_buys,
    run_scan,
    set_clock,
    setup_open_account,
    setup_structuring_alert,
    submit_and_verify_document,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestScanDedupSecondRunCreatesNothing:
    def test_second_scan_same_window_end_creates_zero_alerts(self, api):
        """PRD §3.5: "Deduplication suppresses a new alert when one with the same rule
        code, same account, and same window end already exists in `NEW`,
        `UNDER_REVIEW`, or `ESCALATED_TO_CASE`. Matched `POSTED` transactions become
        `FLAGGED`, and the run reports `alerts_created` and `transactions_flagged`."
        The first run creates 1 alert and flags 3 transactions; re-running on the same
        clock day creates 0 and flags 0.

        Design: Corner/endpoints/scan_dedup_second_run_creates_nothing
        """
        ctx = setup_open_account()
        create_rule(rule_code="STRUCTURING", threshold_amount=10000.00, window_days=2,
                    min_transaction_count=3)
        post_structuring_buys(ctx["account"]["id"], ctx["rep"])

        first = run_scan()
        assert first["alerts_created"] == 1 and first["transactions_flagged"] == 3, (
            f"first run mismatch: {first}"
        )
        second = run_scan()
        assert second["alerts_created"] == 0 and second["transactions_flagged"] == 0, (
            f"dedup must suppress the second run, got {second}"
        )


class TestAlertsFilteredListScopedByAccount:
    def test_account_filter_isolates_alerts(self, api):
        """PRD §3.5: "Alert listings filter by `account_id`, `transaction_id`,
        `rule_id`, or `status`."
        All alerts belong to account A; filtering by account B returns an empty list.

        Design: Corner/endpoints/alerts_filtered_list_scoped_by_account
        """
        set_clock("2026-05-01T00:00:00Z")
        rep = create_rep(full_name="Rep P2", crd_number="CRD-P02")
        cust_a = create_customer(
            rep, customer_type="INDIVIDUAL", full_name="P2A", tax_id="TIN-P02a",
            country_risk_tier="LOW",
        )
        submit_and_verify_document(cust_a["id"], rep, document_number="P-P02a")
        acct_a = create_account(cust_a["id"], rep, product_set=["CASH"])
        approve_account(acct_a["id"])
        cust_b = create_customer(
            rep, customer_type="INDIVIDUAL", full_name="P2B", tax_id="TIN-P02b",
            country_risk_tier="LOW",
        )
        submit_and_verify_document(cust_b["id"], rep, document_number="P-P02b")
        acct_b = create_account(cust_b["id"], rep, product_set=["CASH"])
        approve_account(acct_b["id"])

        create_rule(rule_code="STRUCTURING", threshold_amount=10000.00, window_days=2,
                    min_transaction_count=3)
        post_structuring_buys(acct_a["id"], rep)
        run_scan()

        resp = api_client.list_alerts(
            TEST_USERS["analyst_headers"], params={"account_id": acct_b["id"]}
        )
        list_b, meta_b = validate_paginated(resp)
        assert list_b == [] and meta_b["total_count"] == 0, (
            "account B has no alerts; the filter must not leak account A's"
        )
        resp = api_client.list_alerts(
            TEST_USERS["analyst_headers"], params={"account_id": acct_a["id"]}
        )
        list_a, meta_a = validate_paginated(resp)
        assert len(list_a) == 1 and meta_a["total_count"] == 1


class TestAlertCloseNoActionThenReopen:
    def test_alert_cycle_and_open_alert_count(self, api):
        """PRD §3.5: "Closing with no action moves `UNDER_REVIEW` → `CLOSED_NO_ACTION`
        and records the supplied `rationale` in `close_rationale`. Reopening moves
        `CLOSED_NO_ACTION` → `UNDER_REVIEW` (again, only from `CLOSED_NO_ACTION`, else
        `ERR_ALERT_NOT_ACTIONABLE`). Every one of these transitions recomputes the
        account's `open_alert_count` — the number of its alerts in `NEW` or
        `UNDER_REVIEW`."

        Design: Corner/state_machines/alert_close_no_action_then_reopen
        """
        ctx = setup_structuring_alert(under_review=True)
        alert_id = ctx["alert"]["id"]
        account_id = ctx["account"]["id"]

        resp = api_client.close_alert_no_action(
            alert_id, {"rationale": "benign"}, TEST_USERS["analyst_headers"]
        )
        closed = validate_success(resp)
        assert closed["status"] == "CLOSED_NO_ACTION"
        assert get_account(account_id)["open_alert_count"] == 0

        resp = api_client.reopen_alert(alert_id, TEST_USERS["analyst_headers"])
        reopened = validate_success(resp)
        assert reopened["status"] == "UNDER_REVIEW"
        assert get_account(account_id)["open_alert_count"] == 1, (
            "the cyclic machine returns the alert to the open workload"
        )


class TestAlertEscalateFromNewRejected:
    def test_escalate_requires_under_review(self, api):
        """PRD §3.5: "an `AMLAnalyst` escalates an alert from `UNDER_REVIEW` to
        `ESCALATED_TO_CASE`" — a NEW alert is not in the required state.
        PRD §2.9: "6. Target lifecycle and actionability — the target resource must be
        in a state that permits the operation ... violations surface as the appropriate
        state error from §5" — for alerts that is `ERR_ALERT_NOT_ACTIONABLE` (409), and
        no case is created.

        Design: Corner/state_machines/alert_escalate_from_new_rejected
        """
        ctx = setup_structuring_alert(under_review=False)
        resp = api_client.escalate_alert(ctx["alert"]["id"], TEST_USERS["analyst_headers"])
        error = validate_error(resp, ApiErrorId.ERR_ALERT_NOT_ACTIONABLE)
        assert error["error_id"] == "ERR_ALERT_NOT_ACTIONABLE"
        assert resp.status_code == 409
        assert get_account(ctx["account"]["id"])["open_case_count"] == 0


class TestEscalateReturnsCaseHandle:
    def test_escalate_response_exposes_case_and_case_links_back(self, api):
        """PRD §3.5: "an `AMLAnalyst` escalates an alert from `UNDER_REVIEW` to
        `ESCALATED_TO_CASE`, which creates an `AMLCase` and returns the new `alert_id`,
        `case_id`, and `case_priority`" — "first the alert moves and the case is
        created in `OPEN` with `origin_alert_id` pointing back".
        The structuring alert aggregates 12000.00 over threshold 10000.00: severity
        120 (ratio 1.2 * 100, LOW multiplier 1.0) maps to priority HIGH ("at least 100
        yields `HIGH`").

        Design: Corner/endpoints/escalate_returns_case_handle
        """
        ctx = setup_structuring_alert(under_review=True)
        alert_id = ctx["alert"]["id"]
        escalation = escalate_alert(alert_id)
        assert escalation["alert_id"] == alert_id
        assert escalation["case_priority"] == "HIGH", (
            f"severity 120 in [100, 150) must map to HIGH, got {escalation['case_priority']}"
        )

        resp = api_client.get_case(
            escalation["case_id"], TEST_USERS["analyst_headers"]
        )
        case = validate_success(resp)
        assert case["origin_alert_id"] == alert_id
        assert case["status"] == "OPEN"


class TestAnalystCannotManageMonitoringRules:
    def test_analyst_creating_rule_denied(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target endpoint is
        rejected with `ERR_UNAUTHORIZED_ROLE`."
        PRD §4: `POST /aml/monitoring-rules` is authorized for `SystemAdmin` — "A
        `SystemAdmin` manages reps, monitoring rules, the lost/stolen registry, the
        logical clock, and the daily sweep" (§2.1).

        Design: Corner/rbac/analyst_cannot_manage_monitoring_rules
        """
        create_rep(full_name="Rep B6", crd_number="CRD-B06")
        resp = api_client.create_rule(
            {
                "rule_code": "WIRE_VELOCITY",
                "threshold_amount": 1000.00,
                "window_days": 30,
            },
            TEST_USERS["analyst_headers"],
        )
        error = validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        assert error["error_id"] == "ERR_UNAUTHORIZED_ROLE"
        assert resp.status_code == 403
