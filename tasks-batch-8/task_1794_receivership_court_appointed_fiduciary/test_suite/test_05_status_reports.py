"""Status reports: period contiguity, overlap, overdue flag transitions."""
from test_helpers import (
    RECEIVER,
    ApiErrorId,
    create_case,
    create_claim,
    create_distribution_plan,
    create_status_report,
    determine_claim,
    get_case,
    set_clock,
    validate_error,
    validate_success,
)


class TestReportPeriodContiguity:
    def test_status_report_period_contiguity_required(self, api):
        """PRD §3.6: "The half-open period must not intersect the period of
        any other non-`REJECTED` report of the same case, failing with
        `ERR_REPORT_PERIOD_OVERLAP`, and the report's `period_start` must
        equal the case's current `next_report_period_start` exactly, failing
        with `ERR_REPORT_PERIOD_GAP`. The overlap check is always evaluated
        before the gap check, so a report that collides with an existing one
        surfaces the overlap error even if its start is also wrong."

        Design: Difficulty/resource_temporal_overlap/status_report_period_contiguity_required
        """
        case = create_case(
            appointment_effective_at="2026-08-01T00:00:00Z",
            reporting_interval_days=30,
        )
        # Late-starting first report: gap from the appointment anchor.
        resp1 = api.create_status_report(
            {
                "case_id": case["id"],
                "report_type": "PERIODIC",
                "period_start": "2026-08-15T00:00:00Z",
                "period_end": "2026-09-14T00:00:00Z",
                "narrative": "late start",
            },
            RECEIVER,
        )
        validate_error(resp1, ApiErrorId.ERR_REPORT_PERIOD_GAP)

        ok = api.create_status_report(
            {
                "case_id": case["id"],
                "report_type": "PERIODIC",
                "period_start": "2026-08-01T00:00:00Z",
                "period_end": "2026-08-31T00:00:00Z",
                "narrative": "first period",
            },
            RECEIVER,
        )
        assert validate_success(ok, 201)["status"] == "FILED"

        overlap = api.create_status_report(
            {
                "case_id": case["id"],
                "report_type": "PERIODIC",
                "period_start": "2026-08-15T00:00:00Z",
                "period_end": "2026-09-15T00:00:00Z",
                "narrative": "overlapping",
            },
            RECEIVER,
        )
        validate_error(overlap, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)

        gap = api.create_status_report(
            {
                "case_id": case["id"],
                "report_type": "PERIODIC",
                "period_start": "2026-09-01T00:00:00Z",
                "period_end": "2026-10-01T00:00:00Z",
                "narrative": "gap skipping",
            },
            RECEIVER,
        )
        validate_error(gap, ApiErrorId.ERR_REPORT_PERIOD_GAP)

        adj = api.create_status_report(
            {
                "case_id": case["id"],
                "report_type": "PERIODIC",
                "period_start": "2026-08-31T00:00:00Z",
                "period_end": "2026-09-30T00:00:00Z",
                "narrative": "second period",
            },
            RECEIVER,
        )
        assert validate_success(adj, 201)["status"] == "FILED", (
            "exact adjacency at 2026-08-31 satisfies contiguity"
        )

    def test_status_report_first_period_must_start_at_appointment(self, api):
        """PRD §3.6: "the report's `period_start` must equal the case's
        current `next_report_period_start` exactly, failing with
        `ERR_REPORT_PERIOD_GAP`."
        PRD §2.5: "The case's `next_report_period_start` is the latest
        `period_end` among the case's non-`REJECTED` `PERIODIC` status
        reports; if no such report exists, it is `appointment_effective_at`."

        Design: Difficulty/resource_temporal_overlap/status_report_period_contiguity_required
        """
        case = create_case(appointment_effective_at="2026-08-01T00:00:00Z")
        resp = api.create_status_report(
            {
                "case_id": case["id"],
                "report_type": "PERIODIC",
                "period_start": "2026-08-15T00:00:00Z",
                "period_end": "2026-09-14T00:00:00Z",
                "narrative": "late start",
            },
            RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_GAP)


class TestReportOverdueFlag:
    def test_report_overdue_flag_transitions_with_clock(self, api):
        """PRD §2.5: "The case's `report_overdue` flag is true exactly when
        the current logical time is strictly greater than
        `next_report_period_start` plus `reporting_interval_days` days — at
        the precise instant the interval elapses the report is not yet
        overdue."
        PRD §3.6: "Acceptance moves the report to `ACCEPTED` and advances
        the reporting calendar: `next_report_period_start` and
        `report_overdue` are recomputed"

        Design: Corner/calculations/report_overdue_flag_transitions_with_clock
        """
        case = create_case(
            appointment_effective_at="2026-08-01T00:00:00Z",
            reporting_interval_days=30,
        )
        set_clock("2026-08-31T00:00:00Z")
        assert get_case(case["id"])["report_overdue"] is False, (
            "exactly at the boundary (strictly-greater rule)"
        )

        set_clock("2026-08-31T00:00:01Z")
        assert get_case(case["id"])["report_overdue"] is True, (
            "one second past the boundary with no report filed"
        )

        create_status_report(
            case["id"], report_type="PERIODIC",
            period_start="2026-08-01T00:00:00Z", period_end="2026-08-31T00:00:00Z",
            narrative="period 1",
        )
        assert get_case(case["id"])["report_overdue"] is False, (
            "filing the period-1 report advances next_report_period_start"
        )

    def test_report_overdue_strictly_greater_boundary(self, api):
        """PRD §2.5: "The case's `report_overdue` flag is true exactly when
        the current logical time is strictly greater than
        `next_report_period_start` plus `reporting_interval_days` days — at
        the precise instant the interval elapses the report is not yet
        overdue."

        Design: Corner/calculations/report_overdue_flag_transitions_with_clock
        """
        case = create_case(
            appointment_effective_at="2026-08-01T00:00:00Z",
            reporting_interval_days=30,
        )
        set_clock("2026-08-31T00:00:00Z")
        assert get_case(case["id"])["report_overdue"] is False
        set_clock("2026-08-31T00:00:01Z")
        assert get_case(case["id"])["report_overdue"] is True


class TestOverdueGateOnPlanFiling:
    def test_plan_create_temporal_beats_constraint(self, api):
        """PRD §2.10: "9. The court-calendar gates: a claim filed strictly
        after the bar date (`ERR_CLAIM_BARRED`, HTTP 422) and a plan filing
        or amendment attempted while a periodic report is overdue
        (`ERR_STATUS_REPORT_OVERDUE`, HTTP 422)."
        PRD §2.10: "(c) a second plan in `FILED` or `APPROVED` status on the
        case (`ERR_PLAN_ALREADY_OPEN`)"

        Design: Difficulty/priority_pair_validation_conflict/plan_create_temporal_beats_constraint
        """
        case = create_case(
            appointment_effective_at="2026-08-01T00:00:00Z",
            reporting_interval_days=30,
        )
        claim = create_claim(
            case["id"], creditor_type="GENERAL_UNSECURED", filed_amount_cents=50000,
        )
        determine_claim(claim["id"], "ALLOWED", 50000)
        plan1 = create_distribution_plan(case["id"], reserve_cents=0)
        assert plan1["status"] == "FILED"

        set_clock("2026-09-15T00:00:00Z")  # past 2026-08-31 -> overdue
        resp = api.create_distribution_plan(
            {"case_id": case["id"], "reserve_cents": 0}, RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_STATUS_REPORT_OVERDUE)

    def test_plan_create_blocked_while_report_overdue(self, api):
        """PRD §3.7: "the case's `report_overdue` flag must be false (else
        `ERR_STATUS_REPORT_OVERDUE`, HTTP 422)"

        Design: Difficulty/priority_pair_validation_conflict/plan_create_temporal_beats_constraint
        """
        case = create_case(
            appointment_effective_at="2026-08-01T00:00:00Z",
            reporting_interval_days=30,
        )
        claim = create_claim(
            case["id"], creditor_type="GENERAL_UNSECURED", filed_amount_cents=50000,
        )
        determine_claim(claim["id"], "ALLOWED", 50000)

        set_clock("2026-09-15T00:00:00Z")
        resp = api.create_distribution_plan(
            {"case_id": case["id"], "reserve_cents": 0}, RECEIVER,
        )
        validate_error(resp, ApiErrorId.ERR_STATUS_REPORT_OVERDUE)
