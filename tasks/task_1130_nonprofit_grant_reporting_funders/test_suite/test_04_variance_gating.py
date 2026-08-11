"""Budget-versus-actual variance: dual variants, inclusive threshold, and the
submit gate (PRD §3.6, §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    edit_report,
    post_activity_in_period,
    set_clock,
    setup_active_grant,
    start_report,
    submit_report,
    validate_error,
    validate_success,
    walk_report_to_accepted,
)

OFFICER = TEST_USERS["officer_headers"]

# QUARTERLY 2026-06-01..2027-05-31 periods:
#   P1: 2026-06-01..2026-08-31   P2: 2026-09-01..2026-11-30
P1_DATE = "2026-06-20"
P2_DATE = "2026-09-10"


def _bva_row(summary, budget_line_id, period_index):
    for row in summary["bva"]:
        if row.get("budget_line_id") == budget_line_id and row.get("period_index") == period_index:
            return row
    # Fall back: rows may be keyed differently; locate by line id at minimum.
    for row in summary["bva"]:
        if row.get("budget_line_id") == budget_line_id:
            return row
    raise AssertionError(f"no bva row for line {budget_line_id} in {summary['bva']!r}")


class TestVarianceDualVariant:
    def test_variance_period_only_gates_while_cumulative_below(self, api):
        """PRD §3.6: "The period-only variant is the one that feeds the submit
        gate: a line requires an explanation exactly when its period-only
        actuals are greater than zero and the absolute value of its period-only
        variance percentage is at least the grant's `variance_threshold_pct` —
        the comparator is inclusive."
        PRD §3.6: "In the cumulative variant, actuals sum every active
        allocation on the line whose expense date is on or before the period
        end, with no lower bound, and the budget figure is the sum of the line's
        `period_budgets_cents` entries from period 1 through the current period
        index — the same ledger, different totals."

        Design: Difficulty/dual_variant_calc/variance_period_only_vs_cumulative_gate
        """
        ctx = setup_active_grant(lines=[
            {"category": "PERSONNEL", "budgeted_cents": 50_000_000},
            {"category": "TRAVEL", "budgeted_cents": 20_000_000},
            {"category": "SUPPLIES", "budgeted_cents": 30_000_000},
        ])
        gid = ctx["grant"]["id"]
        l1 = ctx["lines"][0]
        fund = ctx["fund"]
        funder_id = ctx["funder"]["id"]
        r1, r2 = ctx["reports"][0], ctx["reports"][1]

        # P1: 12000000 actual vs 12500000 period budget -> accepted.
        set_clock("2026-06-15T00:00:00Z")
        post_activity_in_period(gid, l1["id"], fund["id"], 12_000_000, P1_DATE)
        start_report(r1["id"])
        edit_report(r1["id"])
        walk_report_to_accepted(r1["id"], funder_id)

        # P2: 14000000 actual vs 12500000 period budget -> +12.00% period-only.
        set_clock("2026-09-15T00:00:00Z")
        post_activity_in_period(gid, l1["id"], fund["id"], 14_000_000, P2_DATE)
        start_report(r2["id"])
        edit_report(r2["id"])

        resp = api.submit_report(r2["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_VARIANCE_EXPLANATION_REQUIRED)

        summary = validate_success(api.get_grant_summary(gid, OFFICER))
        row = _bva_row(summary, l1["id"], 2)
        assert row["period_variance_pct"] == pytest.approx(12.00, abs=0.005), (
            f"period-only variance (14000000-12500000)/12500000 must be 12.00, "
            f"got {row['period_variance_pct']}"
        )
        assert row["cumulative_variance_pct"] == pytest.approx(4.00, abs=0.005), (
            f"cumulative variance (26000000-25000000)/25000000 must be 4.00, "
            f"got {row['cumulative_variance_pct']}"
        )

    def test_variance_cumulative_displayed_on_same_ledger(self, api):
        """PRD §3.6: "In the period-only variant, actuals are the sum of
        `amount_cents` over `ExpenseAllocation` rows on the line that are
        `ACTIVE` and whose parent expense's `expense_date` falls between the
        report period's `period_start` and `period_end` inclusive; the budget
        figure is the line's `period_budgets_cents` entry for that period index.
        In the cumulative variant, actuals sum every active allocation on the
        line whose expense date is on or before the period end, with no lower
        bound."

        Design: Difficulty/dual_variant_calc/variance_period_only_vs_cumulative_gate
        """
        ctx = setup_active_grant(lines=[
            {"category": "PERSONNEL", "budgeted_cents": 50_000_000},
        ])
        gid = ctx["grant"]["id"]
        l1 = ctx["lines"][0]
        fund = ctx["fund"]
        funder_id = ctx["funder"]["id"]
        r1, r2 = ctx["reports"][0], ctx["reports"][1]

        set_clock("2026-06-15T00:00:00Z")
        post_activity_in_period(gid, l1["id"], fund["id"], 12_000_000, P1_DATE)
        start_report(r1["id"])
        edit_report(r1["id"])
        walk_report_to_accepted(r1["id"], funder_id)

        set_clock("2026-09-15T00:00:00Z")
        post_activity_in_period(gid, l1["id"], fund["id"], 14_000_000, P2_DATE)

        summary = validate_success(api.get_grant_summary(gid, OFFICER))
        row = _bva_row(summary, l1["id"], 2)
        # Same ledger, two totals: period actual 14000000 vs cumulative 26000000.
        assert row["period_actual_cents"] == 14_000_000
        assert row["cumulative_actual_cents"] == 26_000_000
        assert row["period_budget_cents"] == 12_500_000
        assert row["cumulative_budget_cents"] == 25_000_000


class TestVarianceThresholdBoundary:
    def test_variance_just_below_threshold_submits_without_explanation(self, api):
        """PRD §3.6: "a line requires an explanation exactly when its period-only
        actuals are greater than zero and the absolute value of its period-only
        variance percentage is at least the grant's `variance_threshold_pct` —
        the comparator is inclusive."
        PRD §2.5: "percentage figures (variance percentages, match progress
        percentages) are expressed as numbers rounded half-up to exactly 2
        decimal places".

        Design: Difficulty/boundary_precision_check/variance_threshold_exactly_at_10pct
        """
        ctx = setup_active_grant(lines=[
            {"category": "PERSONNEL", "budgeted_cents": 50_000_000},
        ])
        gid = ctx["grant"]["id"]
        l1 = ctx["lines"][0]
        fund = ctx["fund"]
        r1 = ctx["reports"][0]

        # P1 actual 13749000 vs period budget 12500000 -> 9.99% (< 10.0).
        set_clock("2026-06-15T00:00:00Z")
        post_activity_in_period(gid, l1["id"], fund["id"], 13_749_000, P1_DATE)
        start_report(r1["id"])
        edit_report(r1["id"])
        resp = api.submit_report(r1["id"], OFFICER)
        data = validate_success(resp)
        assert data["status"] == "SUBMITTED", (
            "9.99% variance is below the inclusive 10.0 threshold and must not "
            "require an explanation"
        )

    def test_variance_exactly_at_threshold_forces_explanation(self, api):
        """PRD §3.4: "every budget line of the grant whose period-only absolute
        variance percentage is at least the grant's `variance_threshold_pct`
        must have a `VarianceExplanation` row (with any non-empty text) on this
        report — otherwise `ERR_VARIANCE_EXPLANATION_REQUIRED` (HTTP 422)."
        PRD §3.6: "the comparator is inclusive."

        Design: Difficulty/boundary_precision_check/variance_threshold_exactly_at_10pct
        """
        ctx = setup_active_grant(lines=[
            {"category": "PERSONNEL", "budgeted_cents": 50_000_000},
        ])
        gid = ctx["grant"]["id"]
        l1 = ctx["lines"][0]
        fund = ctx["fund"]
        r1 = ctx["reports"][0]

        # P1 actual 13750000 vs period budget 12500000 -> exactly +10.00%.
        set_clock("2026-06-15T00:00:00Z")
        post_activity_in_period(gid, l1["id"], fund["id"], 13_750_000, P1_DATE)
        start_report(r1["id"])
        edit_report(r1["id"])
        resp = api.submit_report(r1["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_VARIANCE_EXPLANATION_REQUIRED)
