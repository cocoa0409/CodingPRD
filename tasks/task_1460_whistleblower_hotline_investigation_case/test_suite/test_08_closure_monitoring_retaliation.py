"""Closure notices, monitoring plan schedule, check-in sweeps, retaliation escalation."""
from test_helpers import (
    ApiErrorId,
    create_flag_payload,
    get_case,
    make_admin_headers,
    make_reporter_headers,
    setup_case_closure_ready,
    setup_case_monitoring,
    setup_case_under_investigation,
    validate_error,
    validate_success,
    api_client,
)


class TestMonitoringPlanSchedule:
    def test_plan_window_and_first_checkin_due(self, api):
        """PRD §3.7: "starts its `start_at` at the notice's `acknowledged_at` and
        computes `end_at` as exactly 365 days later ... `next_check_in_due` is
        initially `start_at` plus 30 days".

        Design: Corner/calculations/monitoring_plan_schedule_constants
        """
        ctx = setup_case_monitoring()
        plan = ctx["plan"]
        assert plan["start_at"] == "2026-08-01T00:00:00Z"
        assert plan["end_at"] == "2027-08-01T00:00:00Z"
        assert plan["next_check_in_due"] == "2026-08-31T00:00:00Z"

    def test_missed_count_starts_at_zero(self, api):
        """PRD §3.7: "The clock sweep performs the missed-check-in accounting" — with
        no sweep past the grace window the count is 0.

        Design: Corner/calculations/monitoring_plan_schedule_constants
        """
        ctx = setup_case_monitoring()
        assert ctx["plan"]["missed_checkin_count"] == 0


class TestCheckIn:
    def test_checkin_resets_next_due(self, api):
        """PRD §3.7: "An officer records a check-in while the plan is `ACTIVE` ...
        which stamps `last_check_in_at` and pushes `next_check_in_due` to 30 days
        after the check-in moment".

        Design: Corner/calculations/checkin_resets_next_due_date
        """
        ctx = setup_case_monitoring()
        staff = ctx["staff"]
        api.set_clock("2026-08-10T00:00:00Z", make_admin_headers())
        resp = api.check_in_monitoring_plan(ctx["plan"]["id"], staff["h_off"])
        data = validate_success(resp)
        assert data["last_check_in_at"] == "2026-08-10T00:00:00Z"
        assert data["next_check_in_due"] == "2026-09-09T00:00:00Z"


class TestMissedCheckinSweep:
    def test_sweep_increments_missed_count_once(self, api):
        """PRD §3.7: "each time the current time passes `next_check_in_due` by more
        than a 3-day grace while the plan is `ACTIVE`, the sweep increments
        `missed_checkin_count` by exactly 1 and advances `next_check_in_due` by 30
        days".

        Design: Corner/calculations/missed_checkin_sweep_accounting
        """
        ctx = setup_case_monitoring()
        staff = ctx["staff"]
        # due 2026-08-31; grace end 2026-09-03; now 2026-09-04 -> 1 miss, next due 09-30
        api.set_clock("2026-09-04T00:00:00Z", make_admin_headers())
        plans = api.list_monitoring_plans(ctx["case"]["id"], staff["h_off"]).json()["data"]
        assert plans[0]["missed_checkin_count"] == 1

    def test_sweep_rolls_next_due_forward(self, api):
        """PRD §3.7: "advances `next_check_in_due` by 30 days".

        Design: Corner/calculations/missed_checkin_sweep_accounting
        """
        ctx = setup_case_monitoring()
        staff = ctx["staff"]
        api.set_clock("2026-09-04T00:00:00Z", make_admin_headers())
        plans = api.list_monitoring_plans(ctx["case"]["id"], staff["h_off"]).json()["data"]
        assert plans[0]["next_check_in_due"] == "2026-09-30T00:00:00Z"


class TestAutoAckBoundary:
    def _setup_sent_notice(self, api):
        return setup_case_closure_ready()

    def test_one_second_before_14_days_notice_stays_sent(self, api):
        """PRD §3.7: "the clock sweep auto-acknowledges once the current time reaches
        or passes `sent_at` plus 14 days — the 14-day boundary is inclusive."

        Design: Corner/calculations/auto_ack_fires_at_exactly_14_days
        """
        ctx = self._setup_sent_notice(api)
        staff = ctx["staff"]
        assert ctx["notice"]["status"] == "SENT"
        api.set_clock("2026-08-14T23:59:59Z", make_admin_headers())
        notices = api.list_closure_notices(ctx["case"]["id"], staff["h_off"]).json()["data"]
        assert notices[0]["status"] == "SENT"

    def test_exactly_14_days_auto_ack_fires(self, api):
        """PRD §3.7: "the clock sweep auto-acknowledges once the current time reaches
        or passes `sent_at` plus 14 days — the 14-day boundary is inclusive."
        and "in the same stroke creates the case's monitoring plan and moves the
        case to `MONITORING`".

        Design: Corner/calculations/auto_ack_fires_at_exactly_14_days
        """
        ctx = self._setup_sent_notice(api)
        staff = ctx["staff"]
        api.set_clock("2026-08-15T00:00:00Z", make_admin_headers())
        notices = api.list_closure_notices(ctx["case"]["id"], staff["h_off"]).json()["data"]
        assert notices[0]["status"] == "ACKNOWLEDGED"
        assert notices[0]["acknowledged_at"] == "2026-08-15T00:00:00Z"
        case = get_case(ctx["case"]["id"], staff["h_off"])
        assert case["status"] == "MONITORING"


class TestRetaliationThreshold:
    """Difficulty: retaliation_threshold_three_vs_four (2 tests)."""

    def _monitoring_ctx(self, api):
        return setup_case_monitoring(category="OTHER",
                                     description="Allegation of minor policy lapse")

    def test_score_3_leaves_case_monitoring(self, api):
        """PRD §3.7: "if the new total reaches at least 4 while the case is
        `MONITORING`, the escalation cascade fires" — MANUAL(1)+HR_SIGNAL(2)=3
        stays below the threshold.

        Design: Difficulty/boundary_precision_check/retaliation_threshold_three_vs_four
        """
        ctx = self._monitoring_ctx(api)
        staff = ctx["staff"]
        api.create_retaliation_flag(ctx["case"]["id"], create_flag_payload(
            reported_via="MANUAL", description="Anecdotal cold-shoulder signal",
        ), staff["h_off"])
        api.create_retaliation_flag(ctx["case"]["id"], create_flag_payload(
            reported_via="HR_SIGNAL", description="Manager excluded reporter from meetings",
        ), staff["h_off"])
        case = get_case(ctx["case"]["id"], staff["h_off"])
        assert case["status"] == "MONITORING"
        assert case["retaliation_risk_score"] == 3

    def test_score_exactly_4_escalates(self, api):
        """PRD §3.7: "if the new total reaches at least 4 while the case is
        `MONITORING`, the escalation cascade fires atomically ... the case moves to
        `REOPENED`".

        Design: Difficulty/boundary_precision_check/retaliation_threshold_three_vs_four
        """
        ctx = self._monitoring_ctx(api)
        staff = ctx["staff"]
        api.create_retaliation_flag(ctx["case"]["id"], create_flag_payload(
            reported_via="MANUAL", description="Anecdotal cold-shoulder signal",
        ), staff["h_off"])
        api.create_retaliation_flag(ctx["case"]["id"], create_flag_payload(
            reported_via="HR_SIGNAL", description="Manager excluded reporter from meetings",
        ), staff["h_off"])
        resp = api.create_retaliation_flag(ctx["case"]["id"], create_flag_payload(
            reported_via="MANUAL", description="Performance review suddenly negative",
        ), staff["h_off"])
        f3 = validate_success(resp, expected_status=201)
        assert f3["status"] == "ESCALATED"
        case = get_case(ctx["case"]["id"], staff["h_off"])
        assert case["status"] == "REOPENED"


class TestRetaliationCascadeDepth3:
    """Difficulty: retaliation_reopen_cascade_depth3 (2 tests)."""

    def _escalated_ctx(self, api):
        # Build a case that triages to LOW (OTHER/STAFF/NONE/NONE = 15 -> LOW) so the
        # cascade's LOW->MEDIUM band bump is observable.
        ctx = setup_case_monitoring(
            category="OTHER",
            description="Allegation of minor policy lapse",
            _triage_overrides={"confirmed_category": "OTHER"},
        )
        staff = ctx["staff"]
        r1 = api.create_retaliation_flag(ctx["case"]["id"], create_flag_payload(
            reported_via="HR_SIGNAL", description="Manager excluded reporter from meetings",
        ), staff["h_off"])
        f1 = validate_success(r1, expected_status=201)
        r2 = api.create_retaliation_flag(ctx["case"]["id"], create_flag_payload(
            reported_via="HR_SIGNAL", description="Shift schedule cut after report",
        ), staff["h_off"])
        f2 = validate_success(r2, expected_status=201)
        return ctx, f1, f2

    def test_cascade_escalates_flags_and_reopens_case(self, api):
        """PRD §3.7: "every contributing `OPEN` flag becomes `ESCALATED`; the case
        moves to `REOPENED`, its `severity` is bumped one band (`LOW` to `MEDIUM` to
        `HIGH` to `CRITICAL`, with `CRITICAL` remaining `CRITICAL`) ...
        `reopen_count` rises by 1, and `assigned_investigator_id` is cleared".

        Design: Difficulty/transitive_cascade/retaliation_reopen_cascade_depth3
        """
        ctx, f1, f2 = self._escalated_ctx(api)
        staff = ctx["staff"]
        flags = api.list_retaliation_flags(ctx["case"]["id"], staff["h_off"]).json()["data"]
        by_id = {f["id"]: f for f in flags}
        assert by_id[f1["id"]]["status"] == "ESCALATED"
        assert by_id[f2["id"]]["status"] == "ESCALATED"
        case = get_case(ctx["case"]["id"], staff["h_off"])
        assert case["status"] == "REOPENED"
        assert case["severity"] == "MEDIUM", "LOW bumped one band -> MEDIUM"
        assert case["reopen_count"] == 1
        assert case["assigned_investigator_id"] is None

    def test_cascade_suspends_plan_and_appends_events(self, api):
        """PRD §3.7: "the monitoring plan becomes `SUSPENDED` with
        `next_check_in_due` nulled; `RETALIATION_ESCALATED` and `CASE_REOPENED`
        events are appended".

        Design: Difficulty/transitive_cascade/retaliation_reopen_cascade_depth3
        """
        ctx, _f1, _f2 = self._escalated_ctx(api)
        staff = ctx["staff"]
        plans = api.list_monitoring_plans(ctx["case"]["id"], staff["h_off"]).json()["data"]
        assert plans[0]["status"] == "SUSPENDED"
        assert plans[0]["next_check_in_due"] is None
        # Paginate past the default limit of 10 — the lifecycle up to escalation
        # already produces 11 events before RETALIATION_ESCALATED/CASE_REOPENED.
        events = api.list_case_status_events(ctx["case"]["id"], staff["h_off"],
                                             params={"limit": 100}).json()["data"]
        types = {e["event_type"] for e in events}
        assert "RETALIATION_ESCALATED" in types
        assert "CASE_REOPENED" in types


class TestFlagDismissConservation:
    """Difficulty: flag_dismiss_conserves_risk_score (2 tests)."""

    def test_flag_creation_raises_score(self, api):
        """PRD §3.7: "The case's `retaliation_risk_score` is the sum of the weights
        of its flags that are `OPEN`" with "`HR_SIGNAL` 2".

        Design: Difficulty/compensating_invariant/flag_dismiss_conserves_risk_score
        """
        ctx = setup_case_monitoring(category="OTHER",
                                    description="Allegation of minor policy lapse")
        staff = ctx["staff"]
        api.create_retaliation_flag(ctx["case"]["id"], create_flag_payload(
            reported_via="HR_SIGNAL", description="Manager excluded reporter from meetings",
        ), staff["h_off"])
        case = get_case(ctx["case"]["id"], staff["h_off"])
        assert case["retaliation_risk_score"] == 2

    def test_dismiss_restores_score_and_keeps_monitoring(self, api):
        """PRD §3.7: "An officer may instead dismiss an `OPEN` flag ... which records
        `dismissed_by_id`, moves the flag to `DISMISSED`, and recomputes the score
        with the dismissed flag excluded."

        Design: Difficulty/compensating_invariant/flag_dismiss_conserves_risk_score
        """
        ctx = setup_case_monitoring(category="OTHER",
                                    description="Allegation of minor policy lapse")
        staff = ctx["staff"]
        resp = api.create_retaliation_flag(ctx["case"]["id"], create_flag_payload(
            reported_via="HR_SIGNAL", description="Manager excluded reporter from meetings",
        ), staff["h_off"])
        flag = validate_success(resp, expected_status=201)
        resp2 = api.dismiss_retaliation_flag(flag["id"], staff["h_off"])
        dismissed = validate_success(resp2)
        assert dismissed["status"] == "DISMISSED"
        case = get_case(ctx["case"]["id"], staff["h_off"])
        assert case["retaliation_risk_score"] == 0
        assert case["status"] == "MONITORING"


class TestFlagRules:
    def test_flag_outside_monitoring_window_rejected(self, api):
        """PRD §3.7: "filing against a case in any other status fails with
        `ERR_MONITORING_WINDOW_INACTIVE`".

        Design: Corner/errors/flag_outside_monitoring_window_rejected
        """
        ctx = setup_case_under_investigation()
        resp = api.create_retaliation_flag(
            ctx["case"]["id"], {"description": "Reporter-facing retaliation attempt"},
            make_reporter_headers(ctx["reporter_key"]),
        )
        validate_error(resp, ApiErrorId.ERR_MONITORING_WINDOW_INACTIVE)

    def test_dismiss_twice_rejected(self, api):
        """PRD §3.7: "dismissing from any other state fails with
        `ERR_FLAG_NOT_OPEN`".

        Design: Corner/errors/dismiss_flag_twice_rejected
        """
        ctx = setup_case_monitoring(category="OTHER",
                                    description="Allegation of minor policy lapse")
        staff = ctx["staff"]
        resp = api.create_retaliation_flag(ctx["case"]["id"], create_flag_payload(
            reported_via="MANUAL", description="Anecdotal cold-shoulder signal",
        ), staff["h_off"])
        flag = validate_success(resp, expected_status=201)
        api.dismiss_retaliation_flag(flag["id"], staff["h_off"])
        resp2 = api.dismiss_retaliation_flag(flag["id"], staff["h_off"])
        validate_error(resp2, ApiErrorId.ERR_FLAG_NOT_OPEN)

    def test_checkin_on_suspended_plan_rejected(self, api):
        """PRD §3.7: "An officer records a check-in while the plan is `ACTIVE`
        (otherwise `ERR_PLAN_NOT_ACTIVE`)".

        Design: Corner/errors/checkin_on_suspended_plan_rejected
        """
        ctx = setup_case_monitoring(category="OTHER",
                                    description="Allegation of minor policy lapse")
        staff = ctx["staff"]
        api.create_retaliation_flag(ctx["case"]["id"], create_flag_payload(
            reported_via="HR_SIGNAL", description="Manager excluded reporter from meetings",
        ), staff["h_off"])
        api.create_retaliation_flag(ctx["case"]["id"], create_flag_payload(
            reported_via="HR_SIGNAL", description="Shift schedule cut after report",
        ), staff["h_off"])
        resp = api.check_in_monitoring_plan(ctx["plan"]["id"], staff["h_off"])
        validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ACTIVE)
