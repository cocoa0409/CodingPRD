"""Workload, incentive payout, and measure performance report claims
(PRD §3.8, §3.9).

Payout and in-period rate tests set reporting_lag_days=400 so the registry clock
can move into the report's period month (June 2026) for closures without the
gaps expiring (due_date + lag would otherwise be crossed by the clock advance,
see the expiry sweep in PRD §3.8).
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, assert_payout, assert_performance_report,
    setup_panel_scenario, create_registry, create_published_measure,
    advance_clock, close_gap_via_evidence, submit_evidence, approve_evidence,
    get_care_gap, create_workload, get_workload, create_report, get_report,
    create_projection, get_payout,
    make_admin_headers,
)

JUNE_NOON = "2026-06-10T12:00:00Z"
PM = "pm_1"
QR = "qr_1"


class TestIncentivePayoutRounding:
    def _scenario_with_three_closures(self, api):
        """3 members, all gaps closed in June 2026; workload 2026-06 for pm_1."""
        scenario = setup_panel_scenario(num_members=3, reporting_lag_days=400)
        workload = create_workload(scenario["registry"]["id"], panel_manager_id=PM,
                                   period_key="2026-06")
        advance_clock(scenario["registry"]["id"], JUNE_NOON)
        for gap in scenario["gaps"]:
            close_gap_via_evidence(gap["id"], evidence_type="CHART_REVIEW",
                                   service_date="2026-04-15T00:00:00Z")
        report = create_report(scenario["measure"]["id"], period_key="2026-06")
        return scenario, workload, report

    def test_incentive_payout_per_line_rounding(self, api):
        """PRD §3.9: "The manager's `utilization_ratio` selects a
        `tier_multiplier_bps`: below 0.80 utilization the multiplier is 10000 basis
        points; at least 0.80 but below 1.00 it is 12000; at 1.00 or above it is
        15000. The per-gap line is the base rate of 4500 cents per closed gap,
        multiplied by the tier multiplier and divided by 10000, rounded half up to
        whole cents — and this rounding happens per gap, before any multiplication
        by volume. The `base_amount_cents` is that per-gap line multiplied by
        `closed_gap_count_period`. A `quality_bonus_cents` of 50000 cents is added
        when the measure's `PROVISIONAL` closure rate reaches at least 7000 basis
        points (70 percent), and is zero otherwise. The `total_payout_cents` is the
        base amount plus the quality bonus."

        utilization 3/250 = 0.0120 -> tier 10000; per-gap 4500; base 4500*3 = 13500;
        closure rate 3/3 = 10000 bps >= 7000 -> bonus 50000; total 63500.

        Design: Difficulty/combinatorial_formula/incentive_payout_per_line_rounding
        """
        scenario, workload, report = self._scenario_with_three_closures(api)
        assert report["closure_rate_bps"] == 10000
        payout = create_projection(workload["id"])
        assert_payout(payout)
        assert payout["tier_multiplier_bps"] == 10000
        assert payout["base_amount_cents"] == 13500, (
            f"Expected base 13500, got {payout['base_amount_cents']}")
        assert payout["quality_bonus_cents"] == 50000, (
            f"Expected bonus 50000, got {payout['quality_bonus_cents']}")
        assert payout["total_payout_cents"] == 63500, (
            f"Expected total 63500, got {payout['total_payout_cents']}")

    def test_incentive_payout_base_scales_with_closed_count(self, api):
        """PRD §3.9: "The per-gap line is the base rate of 4500 cents per closed gap,
        multiplied by the tier multiplier and divided by 10000, rounded half up to
        whole cents — and this rounding happens per gap, before any multiplication
        by volume. The `base_amount_cents` is that per-gap line multiplied by
        `closed_gap_count_period`."

        Two closures at tier 10000: base = 4500 * 2 = 9000; rate 2/2 = 10000 bps
        reaches the quality threshold, so total = 9000 + 50000.

        Design: Difficulty/combinatorial_formula/incentive_payout_per_line_rounding
        """
        scenario = setup_panel_scenario(num_members=2, reporting_lag_days=400)
        workload = create_workload(scenario["registry"]["id"], panel_manager_id=PM,
                                   period_key="2026-06")
        advance_clock(scenario["registry"]["id"], JUNE_NOON)
        for gap in scenario["gaps"]:
            close_gap_via_evidence(gap["id"], evidence_type="CHART_REVIEW",
                                   service_date="2026-04-15T00:00:00Z")
        report = create_report(scenario["measure"]["id"], period_key="2026-06")
        assert report["closure_rate_bps"] == 10000
        payout = create_projection(workload["id"])
        assert payout["base_amount_cents"] == 9000, (
            f"Expected base 9000, got {payout['base_amount_cents']}")
        assert payout["total_payout_cents"] == 59000, (
            f"Expected total 59000, got {payout['total_payout_cents']}")


class TestIncentiveTierBoundary:
    def test_incentive_tier_boundary_below_080(self, api):
        """PRD §3.9: "The manager's `utilization_ratio` selects a
        `tier_multiplier_bps`: below 0.80 utilization the multiplier is 10000 basis
        points; at least 0.80 but below 1.00 it is 12000; at 1.00 or above it is
        15000."
        PRD §3.9: "The `utilization_ratio` is the assigned member count divided by
        the workload target of 250 members, rounded half up to four decimal places."

        One assigned member: 1/250 = 0.0040 < 0.80 -> tier 10000; one closure ->
        base = 4500.

        Design: Difficulty/boundary_precision_check/incentive_tier_boundary_at_080
        """
        scenario = setup_panel_scenario(num_members=1, reporting_lag_days=400)
        workload = create_workload(scenario["registry"]["id"], panel_manager_id=PM,
                                   period_key="2026-06")
        advance_clock(scenario["registry"]["id"], JUNE_NOON)
        close_gap_via_evidence(scenario["gaps"][0]["id"],
                               evidence_type="CHART_REVIEW",
                               service_date="2026-04-15T00:00:00Z")
        payout = create_projection(workload["id"])
        assert payout["tier_multiplier_bps"] == 10000, (
            f"utilization 0.0040 is below 0.80: expected tier 10000, "
            f"got {payout['tier_multiplier_bps']}")
        assert payout["base_amount_cents"] == 4500, (
            f"Expected base 4500, got {payout['base_amount_cents']}")

    def test_incentive_tier_boundary_at_exactly_080(self, api):
        """PRD §3.9: "The manager's `utilization_ratio` selects a
        `tier_multiplier_bps`: below 0.80 utilization the multiplier is 10000 basis
        points; at least 0.80 but below 1.00 it is 12000; at 1.00 or above it is
        15000."
        PRD §3.9: "The `utilization_ratio` is the assigned member count divided by
        the workload target of 250 members, rounded half up to four decimal places."

        200 assigned members: 200/250 = 0.8000, exactly "at least 0.80" -> tier
        12000; per-gap line round(4500*12000/10000) = 5400; one closure -> base
        5400; closure rate 1/200 = 50 bps < 7000 -> no bonus.

        Design: Difficulty/boundary_precision_check/incentive_tier_boundary_at_080
        """
        specs = [{"mrn": f"M{i:03d}", "date_of_birth": "1960-01-01T00:00:00Z",
                  "risk_tier": "LOW"} for i in range(200)]
        scenario = setup_panel_scenario(member_specs=specs, reporting_lag_days=400)
        assert scenario["panel"]["member_count"] == 200
        workload = create_workload(scenario["registry"]["id"], panel_manager_id=PM,
                                   period_key="2026-06")
        advance_clock(scenario["registry"]["id"], JUNE_NOON)
        close_gap_via_evidence(scenario["gaps"][0]["id"],
                               evidence_type="CHART_REVIEW",
                               service_date="2026-04-15T00:00:00Z")
        report = create_report(scenario["measure"]["id"], period_key="2026-06")
        assert report["closure_rate_bps"] == 50  # 1/200 -> below the bonus threshold
        payout = create_projection(workload["id"])
        assert payout["tier_multiplier_bps"] == 12000, (
            f"utilization exactly 0.8000 selects tier 12000, "
            f"got {payout['tier_multiplier_bps']}")
        assert payout["base_amount_cents"] == 5400, (
            f"Expected base 5400, got {payout['base_amount_cents']}")
        assert payout["quality_bonus_cents"] == 0
        assert payout["total_payout_cents"] == 5400


class TestEvidenceApproveCascade:
    def _scenario_with_workload_report_and_evidence(self, api):
        scenario = setup_panel_scenario(num_members=1, reporting_lag_days=400)
        workload = create_workload(scenario["registry"]["id"], panel_manager_id=PM,
                                   period_key="2026-06")
        payout_v0 = create_projection(workload["id"])
        report = create_report(scenario["measure"]["id"], period_key="2026-06")
        # Move into the report's period so the closure lands inside the window.
        advance_clock(scenario["registry"]["id"], JUNE_NOON)
        gap_id = scenario["gaps"][0]["id"]
        evidence = submit_evidence(gap_id, evidence_type="CHART_REVIEW",
                                   service_date="2026-04-15T00:00:00Z", submitter_id=PM)
        return scenario, workload, payout_v0, report, gap_id, evidence

    def test_evidence_approve_to_incentive_payout_chain(self, api):
        """PRD §3.6: "The closure then cascades outward: the member's
        `open_gap_count` decrements by one, the workload row of the panel's owner
        increments `closed_gap_count_period` by one, that workload's
        `utilization_ratio` is recomputed, every `PROJECTED` incentive payout for the
        current `period_key` is recomputed under the payout rule of §3.9, and the
        current period's `PROVISIONAL` performance report recomputes its
        `numerator_count` and `closure_rate_bps`."
        PRD §3.6: "An approved record becomes `APPROVED`, the gap becomes `CLOSED`".

        Design: Difficulty/transitive_cascade/evidence_approve_to_incentive_payout_chain
        """
        (scenario, workload, payout_v0, report, gap_id,
         evidence) = self._scenario_with_workload_report_and_evidence(api)
        approve_evidence(evidence["id"], reviewer_id=QR)

        gap_after = get_care_gap(gap_id)
        assert gap_after["status"] == "CLOSED", f"Expected CLOSED, got {gap_after['status']}"

        workload_after = get_workload(workload["id"])
        assert workload_after["closed_gap_count_period"] == 1, (
            f"Expected closed_gap_count_period 1, "
            f"got {workload_after['closed_gap_count_period']}")

        payout_after = get_payout(payout_v0["id"])
        assert payout_after["total_payout_cents"] > payout_v0["total_payout_cents"], (
            f"PROJECTED payout must recompute upward after a closure: "
            f"{payout_v0['total_payout_cents']} -> {payout_after['total_payout_cents']}")

        report_after = get_report(report["id"])
        assert report_after["numerator_count"] == report["numerator_count"] + 1, (
            f"PROVISIONAL numerator must increment: {report['numerator_count']} -> "
            f"{report_after['numerator_count']}")

    def test_evidence_approve_sets_closure_source_and_decrements_member(self, api):
        """PRD §3.6: "An approved record becomes `APPROVED`, the gap becomes
        `CLOSED`, and the gap's `closure_source` is set to `EVIDENCE` — or to
        `APPOINTMENT_COMPLETED` when the evidence derived from a completed
        appointment; gaps closed on the strength of claims-feed submissions record
        `closure_source` as `CLAIMS_FEED`."
        PRD §3.6: "the member's `open_gap_count` decrements by one".

        Design: Difficulty/transitive_cascade/evidence_approve_to_incentive_payout_chain
        """
        (scenario, workload, payout_v0, report, gap_id,
         evidence) = self._scenario_with_workload_report_and_evidence(api)
        member_id = scenario["members"][0]["id"]
        approve_evidence(evidence["id"], reviewer_id=QR)
        gap_after = get_care_gap(gap_id)
        assert gap_after["status"] == "CLOSED"
        assert gap_after.get("closure_source") == "EVIDENCE", (
            f"Chart-review closure records closure_source EVIDENCE, "
            f"got {gap_after.get('closure_source')!r}")
        member_after = get_success_data(api.get_member(member_id, make_admin_headers()))
        assert member_after["open_gap_count"] == 0, (
            f"Expected open_gap_count 0 after closure, got {member_after['open_gap_count']}")


class TestPerformanceReports:
    def test_closure_rate_precision_half_up(self, api):
        """PRD §3.8: "The closure rate is the numerator multiplied by 10000 and
        divided by the denominator, rounded half up to an integer number of basis
        points; when the denominator is zero the rate is null rather than zero."
        PRD §3.8: "The numerator counts denominator members with at least one care
        gap for the measure that transitioned to `CLOSED` inside the period window."

        One of three denominator members closes a gap inside period 2026-06:
        round_half_up(1 * 10000 / 3) = 3333.

        Design: Corner/calculations/closure_rate_precision_half_up
        """
        scenario = setup_panel_scenario(num_members=3, reporting_lag_days=400)
        advance_clock(scenario["registry"]["id"], JUNE_NOON)
        close_gap_via_evidence(scenario["gaps"][0]["id"],
                               evidence_type="CHART_REVIEW",
                               service_date="2026-04-15T00:00:00Z")
        resp = api.create_performance_report(scenario["measure"]["id"],
                                             {"period_key": "2026-06"},
                                             make_admin_headers())
        report = validate_success(resp, 201)
        assert_performance_report(report)
        assert report["denominator_count"] == 3, (
            f"Expected denominator 3, got {report['denominator_count']}")
        assert report["numerator_count"] == 1, (
            f"Expected numerator 1, got {report['numerator_count']}")
        assert report["closure_rate_bps"] == 3333, (
            f"round_half_up(10000/3) must be 3333, got {report['closure_rate_bps']}")

    def test_finalize_report_before_lag_window_rejected(self, api):
        """PRD §3.8: "Finalizing a report requires the clock to have reached the
        period end plus the measure's `reporting_lag_days`; finalizing earlier fails
        with `ERR_RECONCILIATION_WINDOW_OPEN`."

        Design: Corner/endpoints/finalize_report_before_lag_window_rejected
        """
        registry = create_registry(name="R-FIN")
        measure = create_published_measure(registry["id"], reporting_lag_days=30)
        report = create_report(measure["id"], period_key="2026-06")
        # Clock is 2026-05-01, far before 2026-06 period end + 30 days.
        resp = api.finalize_performance_report(report["id"], make_admin_headers())
        validate_error(resp, ApiErrorId.ERR_RECONCILIATION_WINDOW_OPEN)


class TestZeroDenominator:
    def _empty_panel_scenario(self):
        # Cohort accepts ages 70-75; the only member is 40 at the default clock.
        return setup_panel_scenario(
            min_age=70, max_age=75,
            member_specs=[{"mrn": "TOO_YOUNG", "date_of_birth": "1986-01-01T00:00:00Z",
                           "risk_tier": "LOW"}])

    def test_closure_rate_zero_denominator_returns_null(self, api):
        """PRD §3.8: "The closure rate is the numerator multiplied by 10000 and
        divided by the denominator, rounded half up to an integer number of basis
        points; when the denominator is zero the rate is null rather than zero."
        PRD §3.8: "The denominator counts members matching the panel's cohort who are
        `ENROLLED` at evaluation time and have no approved exclusion covering the
        measure whose `[effective_from, effective_until)` window overlaps the
        reporting period."

        No member matches the 70-75 cohort, so the denominator is empty.

        Design: Difficulty/boundary_precision_check/closure_rate_zero_denominator_returns_null
        """
        scenario = self._empty_panel_scenario()
        assert scenario["panel"]["member_count"] == 0
        resp = api.create_performance_report(scenario["measure"]["id"],
                                             {"period_key": "2026-06"},
                                             make_admin_headers())
        report = validate_success(resp, 201)
        assert report["denominator_count"] == 0
        assert report["numerator_count"] == 0
        assert report["closure_rate_bps"] is None, (
            f"Zero denominator must yield null, not zero: {report['closure_rate_bps']!r}")

    def test_zero_denominator_report_is_provisional_and_readable(self, api):
        """PRD §3.8: "An administrator generates a report for a measure by supplying
        a `period_key` in `YYYY-MM` form; the report is created in the `PROVISIONAL`
        variant with `denominator_count`, `numerator_count`, and `closure_rate_bps`
        computed and its `registry_id` denormalized from the measure."
        PRD §3.8: "when the denominator is zero the rate is null rather than zero."

        Design: Difficulty/boundary_precision_check/closure_rate_zero_denominator_returns_null
        """
        scenario = self._empty_panel_scenario()
        report = create_report(scenario["measure"]["id"], period_key="2026-06")
        fetched = get_report(report["id"])
        assert fetched["variant"] == "PROVISIONAL", (
            f"New report must be PROVISIONAL, got {fetched['variant']}")
        assert fetched["closure_rate_bps"] is None
        assert fetched["registry_id"] == scenario["registry"]["id"]
