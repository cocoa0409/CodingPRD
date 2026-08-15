"""Annual settlement calculation: PROVISIONAL vs FINAL variants, MAG proration,
tiered percentage rent, the true-up boundary, and accept-time recalculation."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_rent_settlement,
    assert_settlement_ledger_invariants,
    create_settlement,
    create_settlement_payload,
    file_and_accept_report,
    file_sales_report,
    get_settlement,
    submit_sales_report,
    setup_active_lease,
    setup_settlement_with_reports,
    validate_error,
    validate_success,
)


class TestProvisionalVsFinalVariant:
    def _setup_three_accepted_reports(self):
        """ACTIVE lease (MAG 1,200,000; 8%/10% tiers around a 500,000 breakpoint),
        settlement for 2026, and ACCEPTED reports 2026-01..2026-03 of 2,000,000 each
        (190,000 percentage rent each)."""
        return setup_settlement_with_reports(
            [
                ("2026-01", 2_000_000),
                ("2026-02", 2_000_000),
                ("2026-03", 2_000_000),
            ]
        )

    def test_provisional_variant_projects_unreported_months(
        self, api, analyst_headers
    ):
        """PRD §3.4: "Under `PROVISIONAL` — while the settlement is `ACCRUING`,
        mid-year — every month of the settlement year contributes: months with an
        `ACCEPTED` or `ADJUSTED` report contribute their computed percentage rent,
        and months without one are projected at one-twelfth of the annual guarantee,
        rounded half up, so the accrual reflects expected full-year exposure."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_true_up
        """
        sc = self._setup_three_accepted_reports()
        res = api.recalculate_settlement(sc["settlement"]["id"], analyst_headers)
        settlement = validate_success(res, 200)
        assert_rent_settlement(settlement)
        assert_settlement_ledger_invariants(settlement)
        assert settlement["variant_used"] == "PROVISIONAL"
        # 3 accepted months x 190,000 + 9 unreported months x 100,000 (MAG/12).
        assert settlement["percentage_due_cents"] == 1_470_000
        assert settlement["mag_due_cents"] == 1_200_000
        assert settlement["true_up_due_cents"] == 270_000
        assert settlement["amount_due_cents"] == 1_470_000

    def test_final_variant_counts_only_accepted_reports(self, api, admin_headers,
                                                        analyst_headers):
        """PRD §3.4: "Under `FINAL` — from invoicing onward — only `ACCEPTED` and
        `ADJUSTED` reports count, and unreported months contribute zero percentage
        rent."
        PRD §3.5: "Invoicing performs the final recalculation, sets `variant_used` to
        `FINAL`, stamps `due_date` as the current date plus thirty days, moves the
        settlement to `INVOICED`, and recomputes the lease's `arrears_cents`."

        Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_true_up
        """
        sc = self._setup_three_accepted_reports()
        advance_clock("2027-01-15T00:00:00Z")
        res = api.invoice_settlement(sc["settlement"]["id"], analyst_headers)
        settlement = validate_success(res, 200)
        assert_settlement_ledger_invariants(settlement)
        assert settlement["variant_used"] == "FINAL"
        # Only the 3 ACCEPTED reports (190,000 each); unreported months add zero.
        assert settlement["percentage_due_cents"] == 570_000
        assert settlement["true_up_due_cents"] == 0
        assert settlement["amount_due_cents"] == 1_200_000


class TestProrationAndNestedTrueUp:
    def _setup_mid_month_term_settlement(self):
        """Lease term 2026-04-15..2030-12-31 (April contributes 16/30 days),
        settlement 2026, one ACCEPTED report 2026-05 gross 20,000,000."""
        return setup_settlement_with_reports(
            [("2026-05", 20_000_000)],
            term_start_date="2026-04-15",
        )

    def test_mag_proration_partial_first_month(self, api, analyst_headers):
        """PRD §3.4: "For each calendar month of the year, the covered days are the
        days of that month intersecting the half-open term from `term_start_date`
        inclusive to `term_end_date` exclusive. A month with no covered days
        contributes nothing; a fully covered month contributes a weight of one; a
        partially covered month contributes the fraction of covered days over the
        days in that month, rounded half up to four decimal places. The weights sum
        across the year, and `mag_due_cents` is the lease's `mag_annual_cents`
        multiplied by that total weight and divided by twelve — twelve months per
        lease year — rounded half up to integer cents."

        Design: Difficulty/combinatorial_formula/settlement_proration_nested_max
        """
        sc = self._setup_mid_month_term_settlement()
        advance_clock("2027-01-15T00:00:00Z")
        settlement = validate_success(
            api.invoice_settlement(sc["settlement"]["id"], analyst_headers), 200
        )
        # Weight: 8 full months (May-Dec) + round_half_up(16/30, 4) = 8.5333;
        # mag = round_half_up(1,200,000 * 8.5333 / 12) = 853,330.
        assert settlement["mag_due_cents"] == 853_330

    def test_tiered_percentage_and_true_up_on_invoice(self, api, analyst_headers):
        """PRD §3.4: "Each month applies the two-tier rate structure: when the
        effective gross is at or below `pct_breakpoint_cents`, the entire gross is
        charged at `pct_rate_below_bp`; when above, the breakpoint portion is charged
        at `pct_rate_below_bp` and only the excess above the breakpoint is charged at
        `pct_rate_above_bp`."
        PRD §3.4: "`true_up_due_cents` is the excess of `percentage_due_cents` over
        `mag_due_cents`, floored at zero, so the tenant always owes at least the
        guarantee; `amount_due_cents` is `mag_due_cents` plus `true_up_due_cents`"

        Design: Difficulty/combinatorial_formula/settlement_proration_nested_max
        """
        sc = self._setup_mid_month_term_settlement()
        advance_clock("2027-01-15T00:00:00Z")
        settlement = validate_success(
            api.invoice_settlement(sc["settlement"]["id"], analyst_headers), 200
        )
        # 500,000 at 800bp (40,000) + 19,500,000 at 1000bp (1,950,000) = 1,990,000.
        assert settlement["percentage_due_cents"] == 1_990_000
        assert settlement["mag_due_cents"] == 853_330
        assert settlement["true_up_due_cents"] == 1_136_670
        assert settlement["amount_due_cents"] == 1_990_000
        assert_settlement_ledger_invariants(settlement)


class TestTrueUpBoundary:
    def test_true_up_zero_when_percentage_equals_mag(self, api, analyst_headers):
        """PRD §3.4: "`true_up_due_cents` is the excess of `percentage_due_cents`
        over `mag_due_cents`, floored at zero, so the tenant always owes at least the
        guarantee; `amount_due_cents` is `mag_due_cents` plus `true_up_due_cents`"

        Design: Difficulty/boundary_precision_check/true_up_zero_when_percentage_equals_mag
        """
        # gross 12,100,000 -> 40,000 + 11,600,000 at 1000bp (1,160,000) = 1,200,000,
        # exactly the annual MAG.
        sc = setup_settlement_with_reports([("2026-05", 12_100_000)])
        advance_clock("2027-01-15T00:00:00Z")
        settlement = validate_success(
            api.invoice_settlement(sc["settlement"]["id"], analyst_headers), 200
        )
        assert settlement["percentage_due_cents"] == 1_200_000
        assert settlement["mag_due_cents"] == 1_200_000
        assert settlement["true_up_due_cents"] == 0, (
            "Percentage exactly equal to MAG is not a true-up (excess floored at 0)"
        )
        assert settlement["amount_due_cents"] == 1_200_000

    def test_true_up_positive_when_percentage_exceeds_mag(
        self, api, analyst_headers
    ):
        """PRD §3.4: "`true_up_due_cents` is the excess of `percentage_due_cents`
        over `mag_due_cents`, floored at zero, so the tenant always owes at least the
        guarantee; `amount_due_cents` is `mag_due_cents` plus `true_up_due_cents`"

        Design: Difficulty/boundary_precision_check/true_up_zero_when_percentage_equals_mag
        """
        # gross 12,200,000 -> 40,000 + 11,700,000 at 1000bp (1,170,000) = 1,210,000.
        sc = setup_settlement_with_reports([("2026-05", 12_200_000)])
        advance_clock("2027-01-15T00:00:00Z")
        settlement = validate_success(
            api.invoice_settlement(sc["settlement"]["id"], analyst_headers), 200
        )
        assert settlement["percentage_due_cents"] == 1_210_000
        assert settlement["true_up_due_cents"] == 10_000
        assert settlement["amount_due_cents"] == 1_210_000


class TestMonthlyTierBoundaries:
    def test_monthly_percentage_rent_tier_boundaries(self, api, analyst_headers):
        """PRD §3.4: "The boundary is inclusive: an effective gross exactly equal to
        `pct_breakpoint_cents` stays in the first tier."
        PRD §3.4: "Under `PROVISIONAL` — while the settlement is `ACCRUING`,
        mid-year — every month of the settlement year contributes: months with an
        `ACCEPTED` or `ADJUSTED` report contribute their computed percentage rent,
        and months without one are projected at one-twelfth of the annual guarantee,
        rounded half up, so the accrual reflects expected full-year exposure."

        Design: Corner/calculations/monthly_percentage_rent_tier_boundaries
        """
        sc = setup_active_lease()
        settlement = create_settlement(sc["lease"], period_year=2026)

        # 600,000 straddles the breakpoint: 40,000 + 100,000 at 1000bp = 50,000.
        file_and_accept_report(sc["lease"], sc["tenant"], "2026-01", 600_000)
        first = validate_success(
            api.recalculate_settlement(settlement["id"], analyst_headers), 200
        )
        assert first["percentage_due_cents"] == 1_150_000, (
            "50,000 straddle month + 11 projected months x 100,000"
        )

        # 500,000 is exactly the breakpoint and stays in tier 1: 40,000.
        file_and_accept_report(sc["lease"], sc["tenant"], "2026-02", 500_000)
        second = validate_success(
            api.recalculate_settlement(settlement["id"], analyst_headers), 200
        )
        assert second["percentage_due_cents"] == 1_090_000, (
            "50,000 + 40,000 boundary month + 10 projected months x 100,000"
        )


class TestAcceptCascadeConsistency:
    def test_report_accept_updates_settlement_in_same_request_chain(
        self, api, analyst_headers
    ):
        """PRD §3.3: "Acceptance has a cross-entity cascade: if a settlement exists
        for the lease and the calendar year of the report's `period_month`, that
        settlement is recalculated under the variant implied by its current status
        (§3.4), and the owning lease's `version` increments with its `updated_at`
        refreshed."
        PRD §2.6: "The consistency model is immediate: every mutation is visible in
        the same response that performs it, and derived fields (§2.9) are recomputed
        synchronously as part of the triggering write rather than by any background
        process."

        Design: Corner/consistency_model/report_accept_updates_settlement_in_same_request_chain
        """
        sc = setup_active_lease()
        settlement = create_settlement(sc["lease"], period_year=2026)
        # Initial provisional reading: 12 unreported months x 100,000.
        assert settlement["percentage_due_cents"] == 1_200_000

        report = file_sales_report(sc["lease"], sc["tenant"], "2026-01", 600_000)
        report = submit_sales_report(report, sc["tenant"])
        validate_success(
            api.transition_sales_report(report["id"], {"action": "ACCEPT"}, analyst_headers),
            200,
        )

        after = get_settlement(settlement["id"])
        # 50,000 actual (January) + 11 projected months x 100,000, visible immediately.
        assert after["percentage_due_cents"] == 1_150_000


class TestSettlementUniqueness:
    def test_settlement_year_duplicate_returns_settlement_year_duplicate(
        self, api, admin_headers
    ):
        """PRD §3.4: "Only one settlement may exist per lease and year; a second
        opening is rejected with `ERR_SETTLEMENT_YEAR_DUPLICATE`."

        Design: Corner/validations/settlement_year_duplicate_returns_settlement_year_duplicate
        """
        sc = setup_active_lease()
        create_settlement(sc["lease"], period_year=2026)
        res = api.create_settlement(
            create_settlement_payload(sc["lease"]["id"], period_year=2026),
            admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_SETTLEMENT_YEAR_DUPLICATE)
