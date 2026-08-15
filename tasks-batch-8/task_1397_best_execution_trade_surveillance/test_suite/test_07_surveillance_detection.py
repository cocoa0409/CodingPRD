"""Detection at execution time: front-running scoring and rounding order,
reverse scan, marking-the-close trigger, and the alert score-50 triage
boundary (PRD §3.7)."""
from test_helpers import (
    ApiErrorId,
    approve_trade,
    list_alerts,
    make_employee,
    make_order,
    make_personal_trade,
    report_trade_execution,
    set_clock,
    setup_venue_with_active_arrangement,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import TEST_USERS

CA = TEST_USERS["compliance_admin_headers"]
OPS = TEST_USERS["ops_admin_headers"]
SA = TEST_USERS["surveillance_analyst_headers"]


class TestFrontRunningRounding:
    def _setup_score_23(self):
        """Trade BUY 35 DELT executed 14:00; client SELL 100 DELT executed
        14:45 (delta exactly 2700s, inside the one-hour window, PRD §3.7)."""
        set_clock("2026-08-06T14:00:00Z")
        employee = make_employee(employee_ref="EMP-201", full_name="Rita Book")
        trade = make_personal_trade(employee["id"], symbol="DELT", side="BUY", quantity=35)
        approve_trade(trade["id"])
        report_trade_execution(trade["id"], employee["id"], 5000, "2026-08-06T14:00:00Z")
        venue, arrangement = setup_venue_with_active_arrangement(venue_code="IEXG")
        order = make_order(client_ref="FR1", symbol="DELT", side="SELL", quantity=100,
                           order_type="MARKET", arrival_nbbo_bid_cents=4990,
                           arrival_nbbo_ask_cents=5010, arrangement_id=arrangement["id"])
        set_clock("2026-08-06T15:00:00Z")
        order = validate_success(api_client.order_transition(order["id"], {
            "to_status": "EXECUTED", "executed_price_cents": 4995,
            "executed_at": "2026-08-06T14:45:00Z"}, OPS))
        return employee, trade, order

    def test_front_running_score_sums_then_rounds(self, api):
        """PRD §3.7: "The three factors are summed first and the total is
        rounded half up to a whole integer — rounding factors individually
        first is forbidden." (12.5 + 10.5 + 0 = 23.0 -> 23; per-factor
        rounding would yield 24.)

        Design: Difficulty/combinatorial_formula/front_running_score_final_rounding_only
        """
        _e, _t, order = self._setup_score_23()
        alerts, meta = list_alerts({"related_order_id": order["id"]})
        assert meta["total_count"] == 1, "exactly one FRONT_RUNNING alert for the order"
        assert alerts[0]["alert_type"] == "FRONT_RUNNING"
        assert alerts[0]["score"] == 23, "round_half_up(12.5 + 10.5 + 0) once at the end"

    def test_front_running_alert_audit_echoes(self, api):
        """PRD §3.7: "The alert's `score_inputs` echoes the audit inputs
        `delta_seconds`, `size_ratio`, and `same_side`." and "Each match, in
        either direction, produces one `FRONT_RUNNING` alert carrying the
        matched employee as `subject_employee_id`, the client order as
        `related_order_id`, the personal trade as `related_trade_id`".

        Design: Difficulty/combinatorial_formula/front_running_score_final_rounding_only
        """
        employee, trade, order = self._setup_score_23()
        alerts, _meta = list_alerts({"related_order_id": order["id"]})
        alert = alerts[0]
        assert alert["subject_employee_id"] == employee["id"]
        assert alert["related_trade_id"] == trade["id"]
        assert alert["related_order_id"] == order["id"]
        assert alert["score_inputs"]["delta_seconds"] == 2700
        assert alert["score_inputs"]["same_side"] is False


class TestAlertScoreBoundary:
    def _setup_boundary_alerts(self):
        """Two trades (AAA 100, BBB 30) reported at 14:30; O1 BUY 600 AAA
        executed 15:00 -> score 50; O2 BUY 100 BBB executed 15:06 -> score 49
        (PRD §3.7)."""
        set_clock("2026-08-03T14:00:00Z")
        employee = make_employee(employee_ref="EMP-701", full_name="Sam Edge")
        t1 = make_personal_trade(employee["id"], symbol="AAA", side="BUY", quantity=100)
        approve_trade(t1["id"])
        report_trade_execution(t1["id"], employee["id"], 10000, "2026-08-03T14:30:00Z")
        t2 = make_personal_trade(employee["id"], symbol="BBB", side="BUY", quantity=30)
        approve_trade(t2["id"])
        report_trade_execution(t2["id"], employee["id"], 10000, "2026-08-03T14:30:00Z")

        venue, arrangement = setup_venue_with_active_arrangement(venue_code="NYSE")
        o1 = make_order(client_ref="E1", symbol="AAA", side="BUY", quantity=600,
                        order_type="MARKET", arrangement_id=arrangement["id"])
        set_clock("2026-08-03T15:05:00Z")
        o1 = validate_success(api_client.order_transition(o1["id"], {
            "to_status": "EXECUTED", "executed_price_cents": 10000,
            "executed_at": "2026-08-03T15:00:00Z"}, OPS))
        o2 = make_order(client_ref="E2", symbol="BBB", side="BUY", quantity=100,
                        order_type="MARKET", arrangement_id=arrangement["id"])
        set_clock("2026-08-03T15:10:00Z")
        o2 = validate_success(api_client.order_transition(o2["id"], {
            "to_status": "EXECUTED", "executed_price_cents": 10000,
            "executed_at": "2026-08-03T15:06:00Z"}, OPS))
        a1 = list_alerts({"related_order_id": o1["id"]})[0][0]
        a2 = list_alerts({"related_order_id": o2["id"]})[0][0]
        return a1, a2

    def test_alert_score_50_escalates_but_never_closes(self, api):
        """PRD §3.7: "An alert scored exactly 50 can therefore be escalated
        but never closed as a false positive." and "Closure as a false
        positive — from either `NEW` or `ACKNOWLEDGED` to the terminal
        `CLOSED_FALSE_POSITIVE` — carries the complementary gate: the `score`
        must be strictly below 50 (`ERR_ALERT_SCORE_ABOVE_FP_CEILING`,
        HTTP 409)."

        Design: Difficulty/boundary_precision_check/alert_score_boundary_50_escalate_vs_close
        """
        a1, _a2 = self._setup_boundary_alerts()
        assert a1["score"] == 50, "25 time + 5 size + 20 side pins the boundary score"

        resp = api.alert_transition(a1["id"], {"to_status": "CLOSED_FALSE_POSITIVE"}, SA)
        validate_error(resp, ApiErrorId.ERR_ALERT_SCORE_ABOVE_FP_CEILING)

        validate_success(api.alert_transition(a1["id"], {"to_status": "ACKNOWLEDGED"}, SA))
        escalated = validate_success(api.alert_transition(a1["id"], {"to_status": "ESCALATED"}, SA))
        assert escalated["status"] == "ESCALATED", "score 50 meets the >= 50 escalation gate"

    def test_alert_score_49_closes_but_never_escalates(self, api):
        """PRD §3.7: "From `ACKNOWLEDGED`, escalation moves the alert to
        `ESCALATED` and is gated on gravity: the alert's `score` must be at
        least 50 (`ERR_ALERT_SCORE_BELOW_ESCALATION`, HTTP 409)." and "the
        `score` must be strictly below 50
        (`ERR_ALERT_SCORE_ABOVE_FP_CEILING`, HTTP 409)" for closure.

        Design: Difficulty/boundary_precision_check/alert_score_boundary_50_escalate_vs_close
        """
        _a1, a2 = self._setup_boundary_alerts()
        assert a2["score"] == 49, "20 time + 9 size + 20 side pins one below the boundary"

        # Escalation is admitted only from ACKNOWLEDGED, so acknowledge first;
        # the score gate then fires on the state-admissible attempt.
        validate_success(api.alert_transition(a2["id"], {"to_status": "ACKNOWLEDGED"}, SA))
        resp = api.alert_transition(a2["id"], {"to_status": "ESCALATED"}, SA)
        validate_error(resp, ApiErrorId.ERR_ALERT_SCORE_BELOW_ESCALATION)

        closed = validate_success(api.alert_transition(a2["id"], {"to_status": "CLOSED_FALSE_POSITIVE"}, SA))
        assert closed["status"] == "CLOSED_FALSE_POSITIVE", "score 49 is strictly below 50 and closes"


class TestMarkingTheClose:
    def _setup_moc_order(self, exec_price):
        set_clock("2026-08-10T14:00:00Z")
        venue, arrangement = setup_venue_with_active_arrangement(venue_code="NYSE")
        order = make_order(client_ref="MOC", symbol="ACME", side="BUY", quantity=100,
                           order_type="MARKET_ON_CLOSE",
                           arrival_nbbo_bid_cents=9900, arrival_nbbo_ask_cents=10100,
                           arrangement_id=arrangement["id"],
                           execute={"price_cents": exec_price,
                                    "executed_at": "2026-08-10T14:00:00Z"})
        return order

    def test_marking_close_alert_escalates_to_subjectless_case(self, api):
        """PRD §3.7: "A deviation of 25 basis points or more — the boundary is
        inclusive — creates a `MARKING_THE_CLOSE` alert with a null
        `subject_employee_id`, the order as `related_order_id`, a null
        `related_trade_id`, a `score` of twice the deviation capped at 100".
        PRD §3.7: "Because `MARKING_THE_CLOSE` alerts have a null subject,
        their candidate set is always empty and every such escalation creates
        a fresh subject-less case."

        Design: Corner/state_machines/marking_close_alert_escalates_to_subjectless_case
        """
        order = self._setup_moc_order(10025)  # mid 10000 -> deviation exactly 25 bps
        alerts, meta = list_alerts({"related_order_id": order["id"]})
        assert meta["total_count"] == 1
        alert = alerts[0]
        assert alert["alert_type"] == "MARKING_THE_CLOSE"
        assert alert["score"] == 50, "twice the 25 bps deviation"
        assert alert["subject_employee_id"] is None
        assert alert["related_trade_id"] is None

        escalated = None
        validate_success(api.alert_transition(alert["id"], {"to_status": "ACKNOWLEDGED"}, SA))
        escalated = validate_success(api.alert_transition(alert["id"], {"to_status": "ESCALATED"}, SA))
        assert escalated["status"] == "ESCALATED"
        assert escalated["case_id"] is not None, "escalation opens a case"
        case = validate_success(api.get_case(escalated["case_id"], SA))
        assert case["subject_employee_id"] is None, "the venue-level case has no subject"

    def test_marking_close_below_trigger_creates_no_alert(self, api):
        """PRD §3.7: "A deviation below 25 creates nothing."

        Design: Corner/state_machines/marking_close_below_trigger_creates_no_alert
        """
        order = self._setup_moc_order(10024)  # 24 bps, one under the trigger
        alerts, meta = list_alerts({"related_order_id": order["id"]})
        assert meta["total_count"] == 0 and alerts == []


class TestReverseScan:
    def test_front_running_reverse_scan_on_late_report(self, api):
        """PRD §3.7: "The reverse scan fires when an employee reports an
        execution: every client order with the same `symbol`, in `EXECUTED`
        status, whose `executed_at` falls after the trade's `executed_at`
        (exclusive) and no later than one hour after it (inclusive) matches —
        note the mirror-image bounds."

        Design: Corner/calculations/front_running_reverse_scan_on_late_report
        """
        set_clock("2026-08-03T14:00:00Z")
        employee = make_employee(employee_ref="EMP-901", full_name="Rev Scan")
        trade = make_personal_trade(employee["id"], symbol="ACME", side="BUY", quantity=100)
        approve_trade(trade["id"])  # approved 14:00; not yet reported

        venue, arrangement = setup_venue_with_active_arrangement(venue_code="NYSE")
        order = make_order(client_ref="RS1", symbol="ACME", side="BUY", quantity=100,
                           order_type="MARKET", arrangement_id=arrangement["id"])
        set_clock("2026-08-03T14:50:00Z")
        order = validate_success(api_client.order_transition(order["id"], {
            "to_status": "EXECUTED", "executed_price_cents": 10005,
            "executed_at": "2026-08-03T14:45:00Z"}, OPS))
        before, meta_before = list_alerts({"related_trade_id": trade["id"]})
        assert meta_before["total_count"] == 0, (
            "the forward scan found no reported trades at execution time")

        set_clock("2026-08-03T15:10:00Z")
        report_trade_execution(trade["id"], employee["id"], 10000, "2026-08-03T14:30:00Z")
        after, meta_after = list_alerts({"related_trade_id": trade["id"]})
        assert meta_after["total_count"] == 1, "the report's reverse scan creates the alert"
        alert = after[0]
        assert alert["related_order_id"] == order["id"]
        # delta 900s -> 37.5 time + 30 size + 20 side = 87.5 -> 88.
        assert alert["score"] == 88
