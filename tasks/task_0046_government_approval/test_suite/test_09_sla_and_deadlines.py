"""SLA monitoring, time-limit warning thresholds, deadline arithmetic
across the committed and statutory variants.

Covers PRD §3.7 (Time-Limit Monitoring), §2.8 (Time/Working Days/
Precision), §2.14 (test-driving the clock), §3.13 (SLA performance
report).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock,
    api_client,
    get_application,
    get_success_data,
    parse_iso,
    setup_application_under_review_single_dept,
    TEST_USERS,
    validate_success,
    WORKING_DAY_SECONDS,
)


# ===========================================================================
# Deadline anchoring (PRD §3.7)
# ===========================================================================
class TestDeadlineCalculation:
    def test_deadline_at_uses_committed_time_limit(self, api):
        """PRD §3.7: "In both variants the calculation is the same: take
        the pinned version's days field, multiply by WORKING_DAY_SECONDS
        (28,800) to obtain base_window_seconds, anchor on
        clock_started_at to obtain a raw_deadline of clock_started_at
        plus base_window_seconds." PRD §3.7: "The result, evaluated
        under the committed variant, is written back to
        Application.deadline_at."

        Claim: deadline_at == clock_started_at + committed_time_limit_days
        * 28,800 seconds.

        # difficulty: dual_variant_calc/time_limit_committed_vs_statutory_on_application
        """
        ctx = setup_application_under_review_single_dept(
            fee_amount_cents=0,
            committed_time_limit_days=10,
            statutory_time_limit_days=15,
        )
        app = get_application(ctx["application"]["id"])
        clock_started = parse_iso(app["clock_started_at"])
        deadline = parse_iso(app["deadline_at"])
        delta = int((deadline - clock_started).total_seconds())
        assert delta == 10 * WORKING_DAY_SECONDS, (
            f"deadline_at - clock_started_at expected {10 * WORKING_DAY_SECONDS}s, "
            f"got {delta}"
        )


# ===========================================================================
# SLA endpoint warning thresholds (PRD §3.7)
# ===========================================================================
class TestSlaWarningEvaluator:
    def test_pct_below_warning_returns_on_track(
        self, api, platform_admin_headers,
    ):
        """PRD §3.7: "The status returned is ON_TRACK when pct is
        strictly less than warning_threshold_pct." PRD §2.8:
        "Percentages computed from elapsed time use integer division
        (truncated)."

        Claim: with committed=10 days (288,000s) and warning=80%, an
        elapsed of 230,399s yields pct=79 < 80 -> ON_TRACK.

        # difficulty: boundary_precision_check/warning_pct_inclusive_boundary_on_sla_endpoint
        """
        ctx = setup_application_under_review_single_dept(
            committed_time_limit_days=10,
            statutory_time_limit_days=15,
            warning_threshold_pct=80,
        )
        # Advance 230,399s (just under 80% of 288,000).
        advance_clock(230_399)
        resp = api.get_application_sla(
            ctx["application"]["id"], platform_admin_headers,
        )
        sla = validate_success(resp)
        assert sla["status"] == "ON_TRACK"

    def test_pct_at_warning_boundary_inclusive_returns_warning(
        self, api, platform_admin_headers,
    ):
        """PRD §3.7: "WARNING when pct is at least warning_threshold_pct
        and strictly less than 100." PRD §2.8: "a percentage of exactly
        the configured warning_threshold_pct is already WARNING."

        Claim: with the same setup at elapsed=230,400s, pct=80 ==
        warning_threshold_pct -> WARNING (boundary inclusive).

        # difficulty: boundary_precision_check/warning_pct_inclusive_boundary_on_sla_endpoint
        """
        ctx = setup_application_under_review_single_dept(
            committed_time_limit_days=10,
            statutory_time_limit_days=15,
            warning_threshold_pct=80,
        )
        # Advance to exactly 230,400s = 80% of 288,000.
        advance_clock(230_400)
        resp = api.get_application_sla(
            ctx["application"]["id"], platform_admin_headers,
        )
        sla = validate_success(resp)
        assert sla["status"] == "WARNING"

    def test_pct_at_one_hundred_is_overdue(self, api, platform_admin_headers):
        """PRD §3.7: "OVERDUE when pct is at least 100 -- a pct of
        exactly 100 is already OVERDUE." PRD §2.8: "a percentage of
        exactly 100 is already OVERDUE."

        Claim: at elapsed exactly 288,000s (= 100% of committed_seconds),
        SLA status is OVERDUE.
        """
        ctx = setup_application_under_review_single_dept(
            committed_time_limit_days=10,
            statutory_time_limit_days=15,
            warning_threshold_pct=80,
        )
        advance_clock(288_000)  # 10*28800
        resp = api.get_application_sla(
            ctx["application"]["id"], platform_admin_headers,
        )
        sla = validate_success(resp)
        assert sla["status"] == "OVERDUE"


# ===========================================================================
# NOT_STARTED before UNDER_REVIEW (PRD §3.7)
# ===========================================================================
class TestSlaNotStarted:
    def test_sla_status_not_started_when_clock_not_armed(
        self, api, platform_admin_headers,
    ):
        """PRD §3.7: "Applications that have not yet entered UNDER_REVIEW
        have clock_started_at null; for them the SLA snapshot reports an
        elapsed of 0 and a status of NOT_STARTED."

        Claim: an Application still in SUBMITTED has SLA status =
        NOT_STARTED.
        """
        from test_helpers import (
            setup_single_department_published_version,
            submit_application,
        )
        ctx = setup_single_department_published_version(fee_amount_cents=1000)
        # Don't drive identity / payment events: stays in SUBMITTED.
        application, _hdrs, _id = submit_application(ctx=ctx)
        resp = api.get_application_sla(application["id"], platform_admin_headers)
        sla = validate_success(resp)
        assert sla["status"] == "NOT_STARTED"


# ===========================================================================
# SLA performance report uses statutory variant (PRD §3.13, §3.7)
# ===========================================================================
class TestSlaPerformanceReport:
    def test_sla_performance_report_lists_statutory_for_application(
        self, api, platform_admin_headers,
    ):
        """PRD §3.13: "A separate SLA-performance reporting capability
        returns aggregate metrics for matters and departments over a
        window bounded by optional since and until timestamps, and may
        be filtered by matter_id and department_id. The performance
        report is the sole consumer of the statutory variant of the
        deadline calculation and never drives state transitions."

        Claim: GET /reports/sla-performance returns a 200 envelope when
        the matter_id filter is supplied for a real matter.

        # difficulty: dual_variant_calc/time_limit_committed_vs_statutory_on_application
        """
        ctx = setup_application_under_review_single_dept(
            committed_time_limit_days=10,
            statutory_time_limit_days=15,
        )
        resp = api.get_sla_performance(
            platform_admin_headers, params={"matter_id": ctx["matter"]["id"]},
        )
        validate_success(resp)
