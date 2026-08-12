"""Computed summary: indirect pool, match progress variants, proration, and
burn projections (PRD §3.2, §3.5, §3.6)."""
import pytest

from test_helpers import (
    TEST_USERS,
    allocate,
    create_funder,
    create_grant,
    create_match_contribution,
    create_posted_expense,
    document_contribution,
    edit_report,
    post_activity_in_period,
    set_clock,
    setup_active_grant,
    start_report,
    validate_success,
    verify_contribution,
    walk_report_to_accepted,
    add_budget_line,
    add_fund,
    activate_grant,
    list_reports,
)

OFFICER = TEST_USERS["officer_headers"]


class TestIndirectPool:
    def test_indirect_pool_cap_branch(self, api):
        """PRD §3.6: "The uncapped pool is the direct base multiplied by the rate
        and divided by 100, rounded down to whole cents. When the grant's
        `indirect_cap_cents` is not null, the pool is the smaller of the
        uncapped figure and the cap; when the cap is null the pool is the
        uncapped figure."

        Design: Difficulty/combinatorial_formula/indirect_pool_cap_branch
        """
        ctx = setup_active_grant(
            indirect_rate_pct=10, indirect_cap_cents=2_000_000,
        )
        gid = ctx["grant"]["id"]
        l1 = ctx["lines"][0]
        fund = ctx["fund"]
        set_clock("2026-06-15T00:00:00Z")
        post_activity_in_period(gid, l1["id"], fund["id"], 26_000_000, "2026-06-20")

        summary = validate_success(api.get_grant_summary(gid, OFFICER))
        # uncapped = floor(26000000 * 10 / 100) = 2600000 > cap 2000000
        assert summary["indirect_pool_cents"] == 2_000_000, (
            f"min(2600000 uncapped, 2000000 cap) must bind the cap, got "
            f"{summary['indirect_pool_cents']}"
        )

    def test_indirect_pool_uncapped_branch(self, api):
        """PRD §3.6: "When the grant's `indirect_cap_cents` is not null, the pool
        is the smaller of the uncapped figure and the cap; when the cap is null
        the pool is the uncapped figure."
        PRD §3.6: "The direct base is the sum of `amount_cents` over all
        `ACTIVE` allocations on the grant whose budget line's `category` is
        anything other than `INDIRECT`."

        Design: Difficulty/combinatorial_formula/indirect_pool_cap_branch
        """
        ctx = setup_active_grant(indirect_rate_pct=10)
        gid = ctx["grant"]["id"]
        l1 = ctx["lines"][0]
        fund = ctx["fund"]
        set_clock("2026-06-15T00:00:00Z")
        post_activity_in_period(gid, l1["id"], fund["id"], 26_000_000, "2026-06-20")

        summary = validate_success(api.get_grant_summary(gid, OFFICER))
        assert summary["indirect_pool_cents"] == 2_600_000, (
            f"cap null: pool must be the uncapped floor(26000000*10/100), got "
            f"{summary['indirect_pool_cents']}"
        )

    def test_indirect_de_minimis_federal_branch(self, api):
        """PRD §3.6: "The applicable rate is the grant's `indirect_rate_pct`;
        when that rate is zero (unset) and the awarding funder's `funder_type`
        is `FEDERAL`, the de minimis rate of 10 percent applies instead; when
        the rate is zero and the funder is not federal, the rate is zero."

        Design: Corner/calculations/indirect_de_minimis_federal_branch
        """
        funder = create_funder(funder_type="FEDERAL")
        grant = create_grant(funder["id"])  # indirect_rate_pct defaults to 0
        l1 = add_budget_line(grant["id"], budgeted_cents=100_000_000)
        fund = add_fund(grant["id"], allocated_cents=100_000_000)
        activate_grant(grant["id"])
        set_clock("2026-06-15T00:00:00Z")
        post_activity_in_period(grant["id"], l1["id"], fund["id"], 26_000_000, "2026-06-20")

        summary = validate_success(api.get_grant_summary(grant["id"], OFFICER))
        assert summary["indirect_pool_cents"] == 2_600_000, (
            f"FEDERAL funder with unset rate must apply de minimis 10%: "
            f"floor(26000000*10/100) == 2600000, got "
            f"{summary['indirect_pool_cents']}"
        )


class TestPeriodProration:
    def test_period_proration_remainder_to_final(self, api):
        """PRD §3.2: "The base per-period amount is `adjusted_cents` divided by
        n, rounded down to a whole cent. The remainder — `adjusted_cents` minus
        the base times n — is assigned in full to the final period. Concretely,
        periods 1 through n−1 each receive the base amount, and period n
        receives the base plus the remainder."

        Design: Difficulty/combinatorial_formula/period_proration_remainder_to_final
        """
        ctx = setup_active_grant(
            lines=[{"category": "SUPPLIES", "budgeted_cents": 10_000_003}],
            award_amount_cents=10_000_003,
        )
        line = ctx["lines"][0]
        assert line["period_budgets_cents"] == [2_500_000, 2_500_000, 2_500_000, 2_500_003], (
            f"floor(10000003/4)=2500000 per period with the +3 residual on the "
            f"FINAL period, got {line['period_budgets_cents']}"
        )
        assert sum(line["period_budgets_cents"]) == 10_000_003

    def test_period_proration_conservation_after_activation(self, api):
        """PRD §3.2: "Second, activation computes every budget line's
        `period_budgets_cents`, the per-period proration of the line's
        `adjusted_cents` across the reporting calendar."
        PRD §3.2: "The remainder — `adjusted_cents` minus the base times n — is
        assigned in full to the final period."

        Design: Difficulty/combinatorial_formula/period_proration_remainder_to_final
        """
        ctx = setup_active_grant(
            lines=[{"category": "SUPPLIES", "budgeted_cents": 10_000_003}],
            award_amount_cents=10_000_003,
        )
        fetched = validate_success(
            api.get_budget_line(ctx["lines"][0]["id"], OFFICER)
        )
        # Re-read through the API: the proration persists and conserves total.
        assert fetched["period_budgets_cents"][-1] == 2_500_003
        assert fetched["period_budgets_cents"][:-1] == [2_500_000] * 3


class TestMatchProgress:
    def test_match_progress_verified_vs_pledged_totals(self, api):
        """PRD §3.5: "The verified-only total, `match_verified_only_cents`, sums
        `recognized_value_cents` over contributions in `VERIFIED` status only;
        this is the compliance position and is the figure the `FINAL` report
        submit gate compares against `required_match_cents`. The
        pledged-inclusive total, `match_pledged_inclusive_cents`, sums
        `recognized_value_cents` over contributions in `PLEDGED`, `DOCUMENTED`,
        or `VERIFIED`."
        PRD §3.5: "for `VOLUNTEER_TIME` contributions, the recognized value is
        the `volunteer_hours` multiplied by the standard volunteer rate of 3,150
        cents per hour, rounded to whole cents".

        Design: Difficulty/dual_variant_calc/match_progress_verified_vs_pledged
        """
        ctx = setup_active_grant(required_match_cents=25_000_000)
        gid = ctx["grant"]["id"]
        set_clock("2026-06-15T00:00:00Z")

        m1 = create_match_contribution(  # PLEDGED cash 10000000
            gid, contribution_type="CASH", valuation_basis="ACTUAL_COST",
            documented_value_cents=10_000_000,
        )
        m2 = create_match_contribution(  # VOLUNTEER_TIME 200h -> 630000
            gid, contribution_type="VOLUNTEER_TIME",
            valuation_basis="STANDARD_RATE", volunteer_hours=200,
        )
        document_contribution(m2["id"])  # -> DOCUMENTED
        m3 = create_match_contribution(  # IN_KIND_GOODS 5000000
            gid, contribution_type="IN_KIND_GOODS",
            valuation_basis="FAIR_MARKET", documented_value_cents=5_000_000,
        )
        document_contribution(m3["id"])
        verify_contribution(m3["id"])  # -> VERIFIED

        summary = validate_success(api.get_grant_summary(gid, OFFICER))
        assert summary["match_verified_only_cents"] == 5_000_000
        assert summary["match_pledged_inclusive_cents"] == 15_630_000, (
            f"10000000 + 630000 + 5000000 = 15630000, got "
            f"{summary['match_pledged_inclusive_cents']}"
        )
        assert summary["match_verified_only_pct"] == pytest.approx(20.00, abs=0.005)
        assert summary["match_pledged_inclusive_pct"] == pytest.approx(62.52, abs=0.005)

    def test_match_pledged_contribution_excluded_from_verified_variant(self, api):
        """PRD §3.5: "The verified-only total, `match_verified_only_cents`, sums
        `recognized_value_cents` over contributions in `VERIFIED` status only."
        PRD §3.5: "A new contribution starts in `PLEDGED` status with
        `documented_by_user_id` and `verified_by_user_id` both null."

        Design: Difficulty/dual_variant_calc/match_progress_verified_vs_pledged
        """
        ctx = setup_active_grant(required_match_cents=25_000_000)
        gid = ctx["grant"]["id"]
        set_clock("2026-06-15T00:00:00Z")
        m1 = create_match_contribution(
            gid, contribution_type="CASH", valuation_basis="ACTUAL_COST",
            documented_value_cents=10_000_000,
        )
        assert m1["status"] == "PLEDGED"

        summary = validate_success(api.get_grant_summary(gid, OFFICER))
        assert summary["match_verified_only_cents"] == 0, (
            "a PLEDGED contribution must not count toward the verified-only "
            "compliance total"
        )
        assert summary["match_pledged_inclusive_cents"] == 10_000_000

    def test_match_standard_rate_valuation(self, api):
        """PRD §3.5: "The server immediately computes `recognized_value_cents`:
        for `VOLUNTEER_TIME` contributions, the recognized value is the
        `volunteer_hours` multiplied by the standard volunteer rate of 3,150
        cents per hour, rounded to whole cents; for every other contribution
        type the recognized value equals the `documented_value_cents`."
        PRD §3.5: "A new contribution starts in `PLEDGED` status."

        Design: Corner/calculations/match_standard_rate_valuation
        """
        ctx = setup_active_grant()
        gid = ctx["grant"]["id"]
        resp_data = create_match_contribution(
            gid,
            contribution_type="VOLUNTEER_TIME",
            valuation_basis="STANDARD_RATE",
            volunteer_hours=200,
            documented_value_cents=999_999,
        )
        assert resp_data["recognized_value_cents"] == 630_000, (
            f"200 x 3150 = 630000 must win over documented 999999, got "
            f"{resp_data['recognized_value_cents']}"
        )
        assert resp_data["status"] == "PLEDGED"


class TestBurnRateProjection:
    def test_burn_rate_variant_divergence(self, api):
        """PRD §3.6: "The trailing-average variant takes the mean of per-period
        totals (active allocations by expense date) over the most recent 1
        closed period — a deliberately short window reflecting current momentum
        — and multiplies that average by the total number of report periods,
        rounding to whole cents, yielding `burn_trailing_cents`. The
        cumulative-average variant divides the grant's `total_expended_cents` by
        the number of accepted periods and multiplies by the total number of
        periods, again rounded to whole cents, yielding
        `burn_cumulative_cents`. The `pacing_ratio` divides
        `total_expended_cents` by the pro-rata award — the `award_amount_cents`
        multiplied by the number of accepted periods and divided by the total
        number of periods — and rounds half-up to 2 decimal places."

        Design: Corner/calculations/burn_rate_variant_divergence
        """
        ctx = setup_active_grant(
            lines=[{"category": "PERSONNEL", "budgeted_cents": 50_000_000}],
            variance_threshold_pct=25.0,
        )
        gid = ctx["grant"]["id"]
        l1 = ctx["lines"][0]
        fund = ctx["fund"]
        funder_id = ctx["funder"]["id"]
        r1, r2 = ctx["reports"][0], ctx["reports"][1]

        set_clock("2026-06-15T00:00:00Z")
        post_activity_in_period(gid, l1["id"], fund["id"], 10_000_000, "2026-06-20")
        start_report(r1["id"])
        edit_report(r1["id"])
        walk_report_to_accepted(r1["id"], funder_id)

        set_clock("2026-09-15T00:00:00Z")
        post_activity_in_period(gid, l1["id"], fund["id"], 14_000_000, "2026-09-10")
        start_report(r2["id"])
        edit_report(r2["id"])
        walk_report_to_accepted(r2["id"], funder_id)

        set_clock("2026-12-15T00:00:00Z")
        summary = validate_success(api.get_grant_summary(gid, OFFICER))
        assert summary["burn_trailing_cents"] == 56_000_000, (
            f"trailing window 1: 14000000 x 4 = 56000000, got "
            f"{summary['burn_trailing_cents']}"
        )
        assert summary["burn_cumulative_cents"] == 48_000_000, (
            f"cumulative: (24000000 / 2) x 4 = 48000000, got "
            f"{summary['burn_cumulative_cents']}"
        )
        assert summary["total_expended_cents"] == 24_000_000
        assert summary["pacing_ratio"] == pytest.approx(0.48, abs=0.005)


class TestSummarySmallFixture:
    def test_summary_computed_read_small_fixture(self, api):
        """PRD §3.6: "Two burn projections close out the summary, both derived
        exclusively from the grant's `ACCEPTED` reports ordered by
        `period_index` ascending; periods not yet accepted contribute nothing."
        PRD §3.6: "The uncapped pool is the direct base multiplied by the rate
        and divided by 100, rounded down to whole cents."
        PRD §3.6: "The `pacing_ratio` divides `total_expended_cents` by the
        pro-rata award — the `award_amount_cents` multiplied by the number of
        accepted periods and divided by the total number of periods — and
        rounds half-up to 2 decimal places."

        Design: Corner/endpoints/summary_computed_read_small_fixture
        """
        ctx = setup_active_grant(
            lines=[{"category": "PERSONNEL", "budgeted_cents": 40_000_000}],
            award_amount_cents=40_000_000,
            indirect_rate_pct=10,
        )
        gid = ctx["grant"]["id"]
        l1 = ctx["lines"][0]
        fund = ctx["fund"]
        funder_id = ctx["funder"]["id"]
        r1 = ctx["reports"][0]

        set_clock("2026-06-15T00:00:00Z")
        post_activity_in_period(gid, l1["id"], fund["id"], 10_000_000, "2026-06-20")
        start_report(r1["id"])
        edit_report(r1["id"])
        walk_report_to_accepted(r1["id"], funder_id)

        summary = validate_success(api.get_grant_summary(gid, OFFICER))
        assert summary["total_expended_cents"] == 10_000_000
        assert summary["indirect_pool_cents"] == 1_000_000  # 10% of 10000000
        assert summary["burn_trailing_cents"] == 40_000_000
        assert summary["burn_cumulative_cents"] == 40_000_000
        assert summary["pacing_ratio"] == pytest.approx(1.0, abs=0.005)
        assert summary["match_verified_only_cents"] == 0
