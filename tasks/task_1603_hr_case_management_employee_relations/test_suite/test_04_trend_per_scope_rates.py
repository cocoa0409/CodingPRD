"""Per-scope trend rate precision tests (Difficulty rule 2, instance 2)."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    make_hr_analyst_headers,
    setup_intake_channel,
    setup_employee,
    setup_investigator,
    set_clock,
    run_case_to_closed,
    validate_success,
)


def _build_location(location_code: str, n_employees: int = 6):
    """Create N ACTIVE employees in location; return (reporter, subject, inv trio)."""
    emps = [setup_employee(location_code=location_code) for _ in range(n_employees)]
    reporter = setup_employee(location_code="HQ", department="HR")
    _, inv1 = setup_investigator()
    _, inv2 = setup_investigator()
    _, inv3 = setup_investigator()
    return reporter, emps[0], inv1, inv2, inv3


class TestTrendPerScopeRates:
    def test_per_scope_rate_rounded_half_up_to_two_decimals(self):
        """PRD §3.7: "The per-scope `case_rate_per_100` divides the closed-case
        count by the headcount, multiplies by one hundred, and rounds half-up
        to two decimal places."
        PRD §2.10: "All computed decimal quantities in the system — credibility
        scores, calibration scores, and trend rates — are rounded half-up to
        exactly two decimal places."

        Design: Difficulty/combinatorial_formula/trend_rollup_sum_then_round_pinned
        """
        set_clock("2026-08-01T00:00:00Z")
        channel = setup_intake_channel(
            channel_code="MANAGER_REFERRAL", display_name="Manager Referral",
            default_category="POLICY_VIOLATION", default_severity="LOW",
            sla_business_days=10,
        )
        # LA: 6 ACTIVE + 1 closed case → rate = 1/6 * 100 = 16.666... → 16.67
        reporter, subject, inv1, inv2, inv3 = _build_location("LA", 6)
        run_case_to_closed(
            channel["id"], subject["id"], inv1, inv2, inv3,
            reporter_employee_id=reporter["id"],
            category="POLICY_VIOLATION", severity="LOW",
            action_type="NO_ACTION", severity_points=0,
            substantiation_outcome="UNSUBSTANTIATED",
        )
        set_clock("2026-08-20T00:00:00Z")
        resp = api_client.create_trend_snapshot(
            {"scope_type": "LOCATION", "scope_key": "LA", "window_kind": "ROLLING_90D"},
            make_hr_analyst_headers(),
        )
        ts = validate_success(resp, 201)
        assert ts["closed_case_count"] == 1
        # 1/6 * 100 = 16.6666...; round_half_up to 2dp = 16.67
        assert ts["case_rate_per_100"] == pytest.approx(16.67, abs=1e-6), (
            f"LA rate expected 16.67 (round_half_up of 16.666...), got {ts['case_rate_per_100']}"
        )

    def test_per_scope_rates_equal_across_identical_scopes(self):
        """PRD §2.10: "Trend rates obey a pinned rounding order. Each per-scope
        rate is rounded individually as soon as it is computed; when several
        scopes are combined into a portfolio figure, the unrounded per-scope
        rates are summed first and the sum is rounded half-up to two decimal
        places exactly once. Summing already-rounded per-scope rates is
        forbidden."

        Two identical scopes (LA, NY) each with 6 ACTIVE and 1 closed case:
        per-scope rate is 16.67 each.

        Design: Difficulty/combinatorial_formula/trend_rollup_sum_then_round_pinned
        """
        set_clock("2026-08-01T00:00:00Z")
        channel = setup_intake_channel(
            channel_code="MANAGER_REFERRAL", display_name="Manager Referral",
            default_category="POLICY_VIOLATION", default_severity="LOW",
            sla_business_days=10,
        )
        for loc in ("LA", "NY"):
            reporter, subject, inv1, inv2, inv3 = _build_location(loc, 6)
            run_case_to_closed(
                channel["id"], subject["id"], inv1, inv2, inv3,
                reporter_employee_id=reporter["id"],
                category="POLICY_VIOLATION", severity="LOW",
                action_type="NO_ACTION", severity_points=0,
                substantiation_outcome="UNSUBSTANTIATED",
            )
        set_clock("2026-08-20T00:00:00Z")
        la = validate_success(api_client.create_trend_snapshot(
            {"scope_type": "LOCATION", "scope_key": "LA", "window_kind": "ROLLING_90D"},
            make_hr_analyst_headers(),
        ), 201)
        ny = validate_success(api_client.create_trend_snapshot(
            {"scope_type": "LOCATION", "scope_key": "NY", "window_kind": "ROLLING_90D"},
            make_hr_analyst_headers(),
        ), 201)
        assert la["case_rate_per_100"] == pytest.approx(16.67, abs=1e-6)
        assert ny["case_rate_per_100"] == pytest.approx(16.67, abs=1e-6)
