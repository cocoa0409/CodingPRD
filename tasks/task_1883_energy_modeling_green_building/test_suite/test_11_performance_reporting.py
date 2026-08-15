"""Performance reporting: gap computation and tolerance boundary, closed-day
period tiling, report state gates, and the recertification cycle
(PRD §3.8, §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_report,
    create_report,
    get_project,
    get_success_data,
    make_project_administrator_headers,
    set_clock,
    setup_certified_project,
    setup_certified_project_with_report,
    submit_report,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
ANY = TEST_USERS["any_headers"]


class TestPerformanceGap:
    def test_gap_exactly_at_tolerance_boundary_accepted(self, api):
        """PRD §3.8: "`performance_gap_pct` is the difference between the report's `actual_annual_energy_cost_cents` and the model's `annual_energy_cost_confirmed_only_cents`, divided by that same confirmed-only figure and multiplied by one hundred, rounded half up to two decimal places. `within_tolerance` is true exactly when the absolute value of the gap is at most 15.00, the boundary inclusive — a gap of exactly 15.00 percent in either direction passes."
        PRD §3.8: "Acceptance requires `within_tolerance` to be true — accepting a report whose absolute gap exceeds 15.00 percent fails with `ERR_PERFORMANCE_GAP_EXCEEDED` (HTTP 422)."

        Design: Corner/calculations/performance_gap_tolerance_boundary
        """
        ctx = setup_certified_project_with_report(
            actual=13110000, submit=True, accept=False)
        report = ctx["report"]
        assert report["performance_gap_pct"] == 15.00, (
            "round_half_up(1710000/11400000*100, 2dp)")
        assert report["within_tolerance"] is True, "15.00 <= 15.00 inclusive"

        verified = validate_success(
            api.verify_performance_report(report["id"], "ACCEPT", REVIEWER))
        assert verified["status"] == "ACCEPTED"

    def test_verify_accept_gap_exceeded_blocked(self, api):
        """PRD §3.8: "Acceptance requires `within_tolerance` to be true — accepting a report whose absolute gap exceeds 15.00 percent fails with `ERR_PERFORMANCE_GAP_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/verify_accept_gap_exceeded_blocked
        """
        ctx = setup_certified_project_with_report(
            actual=13120000, submit=True, accept=False)
        report = ctx["report"]
        assert report["performance_gap_pct"] == 15.09
        assert report["within_tolerance"] is False

        resp = api.verify_performance_report(report["id"], "ACCEPT", REVIEWER)
        validate_error(resp, ApiErrorId.ERR_PERFORMANCE_GAP_EXCEEDED)
        after = validate_success(api.get_performance_report(report["id"], ANY))
        assert after["status"] == "SUBMITTED"


class TestReportStateGates:
    def test_report_cycle_and_state_gates(self, api):
        """PRD §3.8: "Submitting, verifying, or revising from the wrong state answers `ERR_INVALID_REPORT_STATE` (HTTP 409)."
        PRD §3.8: "Rejection requires the reviewer to supply a `rejection_reason`, which is recorded on the report; omitting it fails with `ERR_INVALID_REQUEST`."
        PRD §3.8: "Acceptance moves the report `SUBMITTED → ACCEPTED` (its terminal state), rejection moves it `SUBMITTED → REJECTED`, and a `REJECTED` report returns `REJECTED → DRAFT` when the administrator revises it for correction."

        Design: Corner/state_machines/performance_report_cycle_and_state_gates
        """
        ctx = setup_certified_project_with_report(
            actual=12000000, submit=False, accept=False)
        report = ctx["report"]
        admin_id = ctx["members"]["admin"]["id"]
        assert report["performance_gap_pct"] == 5.26
        assert report["within_tolerance"] is True

        # verify while still DRAFT
        resp = api.verify_performance_report(report["id"], "ACCEPT", REVIEWER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REPORT_STATE)

        submit_report(report["id"], admin_id)

        # REJECT without a reason
        resp = api.verify_performance_report(report["id"], "REJECT", REVIEWER)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        rejected = validate_success(
            api.verify_performance_report(
                report["id"], "REJECT", REVIEWER,
                rejection_reason="meter data missing")
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "meter data missing"

        revised = validate_success(
            api.revise_performance_report(
                report["id"], make_project_administrator_headers(admin_id))
        )
        assert revised["status"] == "DRAFT", "cycle REJECTED -> DRAFT"


class TestPeriodTiling:
    def test_shared_boundary_day_is_overlap(self, api):
        """PRD §3.8: "The anchor is the `ACCEPTED` report with the latest `period_end`, if one exists. The required start of a new period is the calendar date of the project's `certified_at` when there is no anchor, and the day immediately after the anchor's `period_end` otherwise. A `period_start` earlier than the required start collides with tiled history and is rejected with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409) — a single shared day is a conflict."

        Design: Difficulty/resource_temporal_overlap/performance_report_closed_tiling
        """
        ctx = setup_certified_project_with_report(actual=12000000)
        admin_id = ctx["members"]["admin"]["id"]

        # Shares the anchor's closing day 2027-12-31 (closed interval).
        resp = api.create_performance_report(
            {"project_id": ctx["project"]["id"],
             "period_start": "2027-12-31T00:00:00Z",
             "period_end": "2028-12-30T00:00:00Z",
             "actual_annual_energy_cost_cents": 12000000},
            make_project_administrator_headers(admin_id),
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)

        # Exact tiling: the day immediately after the anchor's period_end.
        created = validate_success(
            api.create_performance_report(
                {"project_id": ctx["project"]["id"],
                 "period_start": "2028-01-01T00:00:00Z",
                 "period_end": "2028-12-31T00:00:00Z",
                 "actual_annual_energy_cost_cents": 12000000},
                make_project_administrator_headers(admin_id)),
            201,
        )
        assert created["status"] == "DRAFT"

    def test_skipped_day_is_gap(self, api):
        """PRD §3.8: "A `period_start` later than the required start leaves untiled days between periods and is rejected with `ERR_REPORT_PERIOD_GAP` (HTTP 409)."
        PRD §3.8: "The anchor is the `ACCEPTED` report with the latest `period_end`, if one exists. The required start of a new period is the calendar date of the project's `certified_at` when there is no anchor, and the day immediately after the anchor's `period_end` otherwise."

        Design: Difficulty/resource_temporal_overlap/performance_report_closed_tiling
        """
        ctx = setup_certified_project_with_report(actual=12000000)
        admin_id = ctx["members"]["admin"]["id"]

        # 2028-01-02 leaves 2028-01-01 untiled.
        resp = api.create_performance_report(
            {"project_id": ctx["project"]["id"],
             "period_start": "2028-01-02T00:00:00Z",
             "period_end": "2028-12-31T00:00:00Z",
             "actual_annual_energy_cost_cents": 12000000},
            make_project_administrator_headers(admin_id),
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_GAP)

        created = validate_success(
            api.create_performance_report(
                {"project_id": ctx["project"]["id"],
                 "period_start": "2028-01-01T00:00:00Z",
                 "period_end": "2028-12-31T00:00:00Z",
                 "actual_annual_energy_cost_cents": 12000000},
                make_project_administrator_headers(admin_id)),
            201,
        )
        assert created["status"] == "DRAFT"


class TestRecertificationCycle:
    def test_submit_recertification_with_one_report_blocked(self, api):
        """PRD §3.8: "With at least two `ACCEPTED` reports in hand, the administrator enters recertification review, moving the project `PERFORMANCE_REPORTING → RECERTIFICATION_REVIEW`; fewer than two accepted reports fails with `ERR_INSUFFICIENT_PERFORMANCE_REPORTS` (HTTP 409)."

        Design: Corner/validations/submit_recert_with_one_report_blocked
        """
        ctx = setup_certified_project_with_report(actual=12000000)
        resp = api.submit_recertification(
            ctx["project"]["id"],
            make_project_administrator_headers(ctx["members"]["admin"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERFORMANCE_REPORTS)
        assert get_project(ctx["project"]["id"])["status"] == "PERFORMANCE_REPORTING"

    def _drive_to_recertification_review(self, api):
        """CERTIFIED project (certified_at 2027-01-01) + two ACCEPTED tiled
        reports + submit-recertification. Returns the context dict."""
        ctx = setup_certified_project_with_report(actual=12000000)
        admin_id = ctx["members"]["admin"]["id"]
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "PERFORMANCE_REPORTING", (
            "the first report moved CERTIFIED -> PERFORMANCE_REPORTING")

        r2 = create_report(
            ctx["project"]["id"], admin_id,
            period_start="2028-01-01T00:00:00Z",
            period_end="2028-12-31T00:00:00Z",
            actual_annual_energy_cost_cents=12000000)
        submit_report(r2["id"], admin_id)
        accept_report(r2["id"])

        in_review = validate_success(
            api.submit_recertification(
                ctx["project"]["id"], make_project_administrator_headers(admin_id))
        )
        assert in_review["status"] == "RECERTIFICATION_REVIEW"
        return ctx

    def test_recertification_cycle_closes_back_to_certified(self, api):
        """PRD §3.8: "The very first report created for a project moves it `CERTIFIED → PERFORMANCE_REPORTING` automatically, incrementing the project's `version` by one."
        PRD §3.8: "Recertification returns the project `RECERTIFICATION_REVIEW → CERTIFIED`, refreshes `certified_at` to the logical clock's current instant, and restarts the reporting cycle — from `CERTIFIED` to `PERFORMANCE_REPORTING` to `RECERTIFICATION_REVIEW` and back again."

        Design: Difficulty/non_linear_state_machine/project_recertification_cycle
        """
        ctx = self._drive_to_recertification_review(api)
        set_clock("2028-06-01T00:00:00Z")
        recertified = validate_success(
            api.confirm_recertification(ctx["project"]["id"], "RECERTIFY", REVIEWER))
        assert recertified["status"] == "CERTIFIED", (
            "cycle CERTIFIED -> PERFORMANCE_REPORTING -> RECERTIFICATION_REVIEW "
            "-> CERTIFIED closed")

    def test_recertify_refreshes_certified_at_and_retains_rights(self, api):
        """PRD §3.8: "Recertification returns the project `RECERTIFICATION_REVIEW → CERTIFIED`, refreshes `certified_at` to the logical clock's current instant, and restarts the reporting cycle — from `CERTIFIED` to `PERFORMANCE_REPORTING` to `RECERTIFICATION_REVIEW` and back again."
        PRD §3.7: "A `CERTIFY` decision fixes `certified_level` from the threshold table of §3.5 applied to `points_awarded_total`, stamps `certified_at` from the logical clock, sets `plaque_marketing_rights_granted` to true — plaque and marketing rights, granted at this moment and never revoked, retained even if the certification later lapses — and moves the project to `CERTIFIED`."

        Design: Difficulty/non_linear_state_machine/project_recertification_cycle
        """
        ctx = self._drive_to_recertification_review(api)
        assert ctx["project"]["certified_at"] == "2027-01-01T00:00:00Z"

        set_clock("2028-06-01T00:00:00Z")
        recertified = validate_success(
            api.confirm_recertification(ctx["project"]["id"], "RECERTIFY", REVIEWER))
        assert recertified["certified_at"] == "2028-06-01T00:00:00Z", (
            "certified_at refreshed to the logical clock at RECERTIFY")
        assert recertified["certified_level"] == "CERTIFIED", (
            "the achieved level is retained across the cycle")
        assert recertified["plaque_marketing_rights_granted"] is True
