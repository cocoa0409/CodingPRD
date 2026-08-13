"""Surveillance alerts and cases: case selector, parallel dimensions with
cycles, reopen compensation, filing gates, and the late-fee schedule
(PRD §3.7)."""
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    approve_trade,
    escalate_alert_to_case,
    list_alerts,
    make_order,
    make_personal_trade,
    report_trade_execution,
    setup_case_under_investigation,
    setup_comm_case,
    setup_front_running_alert,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

CA = TEST_USERS["compliance_admin_headers"]
FO = TEST_USERS["filing_officer_headers"]
OPS = TEST_USERS["ops_admin_headers"]
SA = TEST_USERS["surveillance_analyst_headers"]


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _disposition_confirmed(case_id):
    return validate_success(api_client.case_review_transition(
        case_id, {"to_status": "DISPOSITIONED", "disposition": "VIOLATION_CONFIRMED"}, SA))


class TestCaseSelector:
    def test_alert_escalate_links_existing_open_case(self, api):
        """PRD §3.7: "The candidate set is any surveillance case whose
        `subject_employee_id` equals the alert's subject and whose
        `review_status` is `OPEN`, `UNDER_INVESTIGATION`, or `REOPENED`".
        "When a candidate exists, the alert's `case_id` is set to it and the
        alert's id is appended to the case's `linked_alert_ids`."

        Design: Corner/state_machines/alert_escalate_links_existing_open_case
        """
        ctx1 = setup_front_running_alert(
            trade_exec_at="2026-08-03T14:30:00Z", order_exec_at="2026-08-03T14:45:00Z",
            symbol="AAA", clock_before_order_exec="2026-08-03T14:50:00Z")
        employee = ctx1["employee"]
        # A second front-running pair on a different symbol for the same employee.
        t2 = make_personal_trade(employee["id"], symbol="BBB", side="BUY", quantity=100)
        approve_trade(t2["id"])
        report_trade_execution(t2["id"], employee["id"], 10000, "2026-08-03T14:52:00Z")
        o2 = make_order(arrangement_id=ctx1["arrangement"]["id"], symbol="BBB",
                        side="BUY", quantity=100, order_type="MARKET")
        set_clock("2026-08-03T14:55:00Z")
        o2 = validate_success(api_client.order_transition(o2["id"], {
            "to_status": "EXECUTED", "executed_price_cents": 10005,
            "executed_at": "2026-08-03T14:53:00Z"}, OPS))
        alerts2, meta2 = list_alerts({"related_order_id": o2["id"]})
        assert meta2["total_count"] == 1
        a2 = alerts2[0]

        a1_esc = escalate_alert_to_case(ctx1["alert"]["id"])
        case_id = a1_esc["case_id"]
        assert case_id is not None

        a2_esc = escalate_alert_to_case(a2["id"])
        assert a2_esc["case_id"] == case_id, "second escalation links the existing open case"
        case = validate_success(api.get_case(case_id, SA))
        assert case["review_status"] == "OPEN"
        assert set(case["linked_alert_ids"]) == {ctx1["alert"]["id"], a2["id"]}, (
            "the single case carries both alerts")


class TestCaseParallelDimensions:
    def test_case_reopen_blocked_while_filing_in_flight(self, api):
        """PRD §3.7: "Reopening moves a disposed case from `DISPOSITIONED` to
        `REOPENED` and is blocked while a filing is in flight —
        `filing_status` of `SUBMITTED` or `ACKNOWLEDGED` rejects the reopen
        with `ERR_FILING_IN_FLIGHT` (HTTP 409)." PRD §3.7: "filing on or
        before `filing_due_at` — the boundary is inclusive — yields a
        `late_fee_cents` of zero".

        Design: Difficulty/non_linear_state_machine/case_parallel_dimensions_with_cycles
        """
        ctx = setup_case_under_investigation()
        case = ctx["case"]
        # Clock is 2026-08-03T14:50:00Z at disposition; due = +30 days.
        dispositioned = _disposition_confirmed(case["id"])
        assert dispositioned["filing_status"] == "DRAFT", (
            "a confirmed violation opens the filing dimension")

        submitted = validate_success(api_client.case_filing_transition(
            case["id"], {"to_status": "SUBMITTED"}, FO))
        assert submitted["late_fee_cents"] == 0, "submitted at the disposition instant: on time"
        assert submitted["filing_submitted_at"] is not None

        resp = api_client.case_review_transition(case["id"], {"to_status": "REOPENED"}, SA)
        validate_error(resp, ApiErrorId.ERR_FILING_IN_FLIGHT)

    def test_case_rejection_cycle_then_reopen_compensates(self, api):
        """PRD §3.7: "A regulator's rejection returns it from `SUBMITTED` to
        `DRAFT` for amendment". PRD §3.7: "Reopening compensates thoroughly:
        every linked alert drops from `ESCALATED` back to `ACKNOWLEDGED` with
        its `case_id` cleared; a `DRAFT` filing is voided — `filing_status`
        returns to `NOT_REQUIRED`, `filing_due_at` and `filing_submitted_at`
        are cleared, and `late_fee_cents` resets to zero". PRD §3.7: "A
        reopened case returns to `UNDER_INVESTIGATION` through the same
        transition as a fresh one."

        Design: Difficulty/non_linear_state_machine/case_parallel_dimensions_with_cycles
        """
        ctx = setup_case_under_investigation()
        case = ctx["case"]
        _disposition_confirmed(case["id"])
        validate_success(api_client.case_filing_transition(case["id"], {"to_status": "SUBMITTED"}, FO))
        # Regulator rejection returns the filing to DRAFT.
        rejected = validate_success(api_client.case_filing_transition(case["id"], {"to_status": "DRAFT"}, FO))
        assert rejected["filing_status"] == "DRAFT"

        reopened = validate_success(api_client.case_review_transition(
            case["id"], {"to_status": "REOPENED"}, SA))
        assert reopened["review_status"] == "REOPENED"
        assert reopened["filing_status"] == "NOT_REQUIRED", "the draft filing is voided"
        assert reopened["filing_due_at"] is None
        assert reopened["late_fee_cents"] == 0
        assert reopened["disposition"] is None

        alert = validate_success(api_client.get_alert(ctx["alert"]["id"], SA))
        assert alert["status"] == "ACKNOWLEDGED", "reopen compensation drops the alert back"
        assert alert["case_id"] is None, "reopen compensation clears the alert's case link"

        again = validate_success(api_client.case_review_transition(
            case["id"], {"to_status": "UNDER_INVESTIGATION"}, SA))
        assert again["review_status"] == "UNDER_INVESTIGATION", (
            "the review dimension completes its cycle")


class TestReopenRoundtripInvariant:
    def test_disposition_then_reopen_conserves_open_case_count(self, api):
        """PRD §3.1: "`open_case_count` is the number of surveillance cases
        whose `subject_employee_id` is this employee and whose `review_status`
        is `OPEN`, `UNDER_INVESTIGATION`, or `REOPENED` — a disposed case
        stops counting unless it is later reopened."

        Design: Difficulty/compensating_invariant/case_disposition_reopen_roundtrip_conserves_open_case_count
        """
        ctx = setup_case_under_investigation()
        employee_id = ctx["employee"]["id"]
        case = ctx["case"]

        before = validate_success(api.get_employee(employee_id, SA))
        assert before["open_case_count"] == 1
        _disposition_confirmed(case["id"])
        mid = validate_success(api.get_employee(employee_id, SA))
        assert mid["open_case_count"] == 0, "disposition drops the conserved quantity"
        validate_success(api.case_review_transition(case["id"], {"to_status": "REOPENED"}, SA))
        after = validate_success(api.get_employee(employee_id, SA))
        assert after["open_case_count"] == 1, "reopen restores it — no drift across the round trip"

    def test_reopen_voids_filing_and_compensates_alerts(self, api):
        """PRD §3.7: "When none exists, a fresh case is created with the
        alert's subject (possibly null), `opened_from` set to `ALERT`,
        `review_status` `OPEN`, and the alert as its first linked alert, and
        the alert's `case_id` points at it." and, on reopen, "every linked
        alert drops from `ESCALATED` back to `ACKNOWLEDGED` with its `case_id`
        cleared" — after which the alert may be escalated again into the
        reopened case (candidate set includes `REOPENED`).

        Design: Difficulty/compensating_invariant/case_disposition_reopen_roundtrip_conserves_open_case_count
        """
        ctx = setup_case_under_investigation()
        case = ctx["case"]
        _disposition_confirmed(case["id"])
        validate_success(api.case_review_transition(case["id"], {"to_status": "REOPENED"}, SA))

        re_escalated = validate_success(api.alert_transition(
            ctx["alert"]["id"], {"to_status": "ESCALATED"}, SA))
        assert re_escalated["status"] == "ESCALATED"
        assert re_escalated["case_id"] == case["id"], (
            "re-escalation from ACKNOWLEDGED re-links the same reopened case")


class TestFilingGatesAndFees:
    def test_filing_submit_on_unfounded_case_rejected(self, api):
        """PRD §3.7: "the submit requires the filing to be in `DRAFT` — a case
        whose filing never opened rejects the submit with
        `ERR_FILING_NOT_REQUIRED` (HTTP 409)" and "An unfounded disposition
        leaves `filing_status` at `NOT_REQUIRED`."

        Design: Corner/state_machines/filing_submit_on_unfounded_case_rejected
        """
        ctx = setup_comm_case(body_term_weight=100, clock_start="2026-08-03T14:00:00Z")
        case = ctx["case"]
        validate_success(api.case_review_transition(case["id"], {"to_status": "UNDER_INVESTIGATION"}, SA))
        dispositioned = validate_success(api.case_review_transition(
            case["id"], {"to_status": "DISPOSITIONED", "disposition": "UNFOUNDED"}, SA))
        assert dispositioned["filing_status"] == "NOT_REQUIRED"

        resp = api.case_filing_transition(case["id"], {"to_status": "SUBMITTED"}, FO)
        validate_error(resp, ApiErrorId.ERR_FILING_NOT_REQUIRED)

    def test_late_filing_fee_boundaries_and_cap(self, api):
        """PRD §3.7: "`filing_due_at` is set to the disposition instant plus
        30 days." and "filing on or before `filing_due_at` — the boundary is
        inclusive — yields a `late_fee_cents` of zero; filing strictly late,
        even by one second, incurs a base fee of 50,000 cents plus 5,000 cents
        per whole day late (partial days discarded), capped at 500,000 cents."
        and "resubmission recomputes the late fee against the unchanged
        `filing_due_at`."

        Design: Corner/calculations/late_filing_fee_boundaries_and_cap
        """
        ctx = setup_comm_case(body_term_weight=100, clock_start="2026-08-03T14:00:00Z")
        case = ctx["case"]
        validate_success(api.case_review_transition(case["id"], {"to_status": "UNDER_INVESTIGATION"}, SA))
        set_clock("2026-08-03T14:55:00Z")
        dispositioned = _disposition_confirmed(case["id"])
        due = _parse(dispositioned["filing_due_at"])
        assert due == _parse(dispositioned["dispositioned_at"]) + timedelta(days=30)
        assert due == datetime(2026, 9, 2, 14, 55, tzinfo=due.tzinfo)

        def _submit():
            return validate_success(api.case_filing_transition(
                case["id"], {"to_status": "SUBMITTED"}, FO))

        def _reject():
            validate_success(api.case_filing_transition(case["id"], {"to_status": "DRAFT"}, FO))

        # Exactly at the due instant: on time (boundary inclusive).
        set_clock("2026-09-02T14:55:00Z")
        assert _submit()["late_fee_cents"] == 0
        _reject()
        # One second late: base fee, zero whole days.
        set_clock("2026-09-02T14:55:01Z")
        assert _submit()["late_fee_cents"] == 50000
        _reject()
        # One whole day late: 50000 + 5000*1.
        set_clock("2026-09-03T14:55:00Z")
        assert _submit()["late_fee_cents"] == 55000
        _reject()
        # 200 days late: 50000 + 5000*200 = 1050000 hits the 500000 cap.
        set_clock("2027-03-21T14:55:00Z")
        assert _submit()["late_fee_cents"] == 500000


class TestSharedReadAccess:
    def test_all_roles_share_read_access(self, api):
        """PRD §4: GET /surveillance/surveillance-cases/{id} is authorized for
        "OpsAdmin, ComplianceAdmin, SurveillanceAnalyst, FilingOfficer,
        BestExAnalyst, CommitteeMember, CoveredEmployee" — a FilingOfficer
        reads a case even though case transitions are analyst-only.

        Design: Corner/rbac/all_roles_share_read_access
        """
        ctx = setup_comm_case(body_term_weight=100)
        case = validate_success(api.get_case(ctx["case"]["id"], FO))
        assert case["review_status"] == "OPEN"
        assert case["opened_from"] == "COMM_REVIEW"
