"""Rent and commission calculations: net effective rent, total consideration,
effective commission rate, and the commission split.

Covers Difficulty queue rules dual_variant_calc and combinatorial_formula, plus
Corner-queue calculation instances. All literal expected values are PRD-derivable
from §3.7 (net effective rent / consideration) and §3.8 (commission rate / split).
"""
import pytest
from test_helpers import (
    get_success_data, validate_success,
    make_listing_broker_headers, make_tenant_broker_headers,
    setup_prospect_deal, submit_first_proposal,
    setup_executed_deal, get_commission_splits_for_deal, split_by_side,
    assert_commission_conserves_total, assert_deal,
)


class TestNetEffectiveRent:
    def test_net_effective_rent_amortizes_free_rent_and_ti(self, api):
        """PRD §3.7: "From that, subtract a free-rent credit equal to `base_rent_psf_yr` multiplied by
        `free_rent_months` divided by twelve — the credit is always valued at the
        year-one base rate, never at an escalated rate — and subtract
        `ti_allowance_psf`. Divide the resulting net total per square foot by the
        term expressed in years (`term_months` divided by twelve), and round that
        single quotient half up to two decimal places."

        Design: Difficulty/dual_variant_calc/net_vs_gross_effective_rent_on_proposal
        """
        ctx = setup_prospect_deal(
            co_broke=True, rentable_sf=5000, asking_rent_psf_yr=60, term_months=36,
            annual_escalation_pct=0.03, max_rent_psf_yr=70)
        prop = submit_first_proposal(
            ctx, from_side="LISTING", base_rent_psf_yr=60, term_months=36,
            free_rent_months=3, ti_allowance_psf=25, annual_escalation_pct=0.03)
        assert prop["net_effective_rent_psf_yr"] == 48.48, (
            f"net effective rent should be 48.48, got {prop['net_effective_rent_psf_yr']}")
        assert prop["outcome"] == "PENDING"

    def test_net_effective_rent_diverges_from_gross_on_same_inputs(self, api):
        """PRD §3.7: "A gross effective rent is the same figure computed without the
        free-rent and tenant-improvement subtractions — the gross total per square foot
        divided by the term in years, rounded half up to two decimal places — and the
        spread between gross and net is the concession value; this gross variant is
        reported for comparison but is not stored."

        Design: Difficulty/dual_variant_calc/net_vs_gross_effective_rent_on_proposal
        """
        # net (stored) reflects the concession subtraction; with free=3 and ti=25 the
        # stored net (48.48) must be strictly below the gross-equivalent figure (61.82),
        # proving the free-rent + TI subtraction was applied.
        ctx = setup_prospect_deal(
            co_broke=True, rentable_sf=5000, asking_rent_psf_yr=60, term_months=36,
            annual_escalation_pct=0.03, max_rent_psf_yr=70)
        prop = submit_first_proposal(
            ctx, from_side="LISTING", base_rent_psf_yr=60, term_months=36,
            free_rent_months=3, ti_allowance_psf=25, annual_escalation_pct=0.03)
        assert prop["net_effective_rent_psf_yr"] == 48.48
        # A zero-concession proposal on the same gross stream yields the gross figure 61.82.
        ctx2 = setup_prospect_deal(
            co_broke=True, rentable_sf=5000, asking_rent_psf_yr=60, term_months=36,
            annual_escalation_pct=0.03, max_rent_psf_yr=70, suite_no="301")
        prop2 = submit_first_proposal(
            ctx2, from_side="LISTING", base_rent_psf_yr=60, term_months=36,
            free_rent_months=0, ti_allowance_psf=0, annual_escalation_pct=0.03)
        assert prop2["net_effective_rent_psf_yr"] == 61.82, (
            f"zero-concession net equals gross 61.82, got {prop2['net_effective_rent_psf_yr']}")
        assert prop2["net_effective_rent_psf_yr"] > prop["net_effective_rent_psf_yr"]

    def test_net_effective_rent_nonlinear_escalated_stream(self, api):
        """PRD §3.7: "for each year the applicable rate is `base_rent_psf_yr` multiplied by
        one plus `annual_escalation_pct` raised to the power of that year's index, and the
        rate contributes for the fraction of the year actually within the term —
        twelve-twelfths for every full year and, for a final partial year, the number of
        remaining months over twelve."

        Design: Difficulty/combinatorial_formula/net_effective_rent_nonlinear_three_input
        """
        ctx = setup_prospect_deal(
            co_broke=True, rentable_sf=4000, asking_rent_psf_yr=50, term_months=24,
            max_rent_psf_yr=80)
        prop = submit_first_proposal(
            ctx, from_side="TENANT", base_rent_psf_yr=50, term_months=24,
            free_rent_months=2, ti_allowance_psf=10, annual_escalation_pct=0.05)
        assert prop["net_effective_rent_psf_yr"] == 42.08, (
            f"net effective rent should be 42.08, got {prop['net_effective_rent_psf_yr']}")

    def test_net_effective_rent_stored_on_proposal_outcome_pending(self, api):
        """PRD §3.5: "A proposal's `outcome` is system-managed and starts `PENDING`, and the round's net
        effective rent is computed and stored on it as `net_effective_rent_psf_yr`
        as §3.7 defines."

        Design: Difficulty/combinatorial_formula/net_effective_rent_nonlinear_three_input
        """
        # Same nonlinear three-input package, authored as a freshly-created PENDING round.
        ctx = setup_prospect_deal(
            co_broke=True, rentable_sf=4000, asking_rent_psf_yr=50, term_months=24,
            max_rent_psf_yr=80, suite_no="724")
        prop = submit_first_proposal(
            ctx, from_side="LISTING", base_rent_psf_yr=50, term_months=24,
            free_rent_months=2, ti_allowance_psf=10, annual_escalation_pct=0.05)
        assert prop["outcome"] == "PENDING"
        assert prop["net_effective_rent_psf_yr"] == 42.08, (
            "net effective rent stored on the proposal equals 42.08")


class TestCommissionSplit:
    def test_in_house_split_pays_listing_everything(self, api):
        """PRD §3.8: "For an in-house deal — one where `is_co_broke` is false because both sides belong to
        the same brokerage — the listing side receives the entire commission
        (`total_commission` rounded half up to two decimal places) and a `PROCURING`
        row is still written with an `amount` of 0.00 for ledger completeness."

        Design: Difficulty/dual_variant_calc/co_broke_vs_in_house_commission_split
        """
        ctx = setup_executed_deal(
            co_broke=False, base_rent_psf_yr=40, term_months=120, annual_escalation_pct=0,
            rentable_sf=5000, asking_rent_psf_yr=40, default_commission_pct=0.06)
        deal = get_success_data(api.get_deal(ctx["deal"]["id"], make_listing_broker_headers(ctx["lb"]["id"])))
        assert deal["is_co_broke"] is False
        assert deal["total_commission"] == 100000.00, (
            f"in-house total_commission should be 100000.00, got {deal['total_commission']}")
        splits = get_commission_splits_for_deal(ctx)
        assert split_by_side(splits, "LISTING")["amount"] == 100000.00
        assert split_by_side(splits, "PROCURING")["amount"] == 0.00

    def test_in_house_deal_flag_is_false_same_brokerage(self, api):
        """PRD §3.8: "For an in-house deal — one where `is_co_broke` is false because both sides belong to
        the same brokerage — the listing side receives the entire commission
        (`total_commission` rounded half up to two decimal places)".

        Design: Difficulty/dual_variant_calc/co_broke_vs_in_house_commission_split
        """
        ctx = setup_executed_deal(
            co_broke=False, base_rent_psf_yr=40, term_months=120, annual_escalation_pct=0,
            rentable_sf=5000, asking_rent_psf_yr=40, default_commission_pct=0.06, suite_no="501")
        deal = get_success_data(api.get_deal(ctx["deal"]["id"], make_listing_broker_headers(ctx["lb"]["id"])))
        assert deal["is_co_broke"] is False
        splits = get_commission_splits_for_deal(ctx)
        # PROCURING row exists for ledger completeness with amount 0.00.
        assert split_by_side(splits, "PROCURING")["amount"] == 0.00
        assert split_by_side(splits, "LISTING")["amount"] == deal["total_commission"]

    def test_co_broke_split_listing_is_residual_not_independently_rounded(self, api):
        """PRD §3.8: "the procuring side's `amount` is `total_commission` multiplied by the listing's
        `co_broke_offered_pct`, rounded half up to two decimal places, and the
        listing side's `amount` is the remainder: `total_commission` minus the
        procuring amount, taken as a residual rather than independently rounded, so
        that the two amounts sum to `total_commission` exactly."

        Design: Difficulty/combinatorial_formula/commission_residual_rounding_order
        """
        ctx = setup_executed_deal(
            co_broke=True, base_rent_psf_yr=26.25, term_months=24, annual_escalation_pct=0,
            rentable_sf=3000, asking_rent_psf_yr=26.25, co_broke_offered_pct=0.3333,
            default_commission_pct=0.06, max_rent_psf_yr=40)
        deal = get_success_data(api.get_deal(ctx["deal"]["id"], make_listing_broker_headers(ctx["lb"]["id"])))
        assert deal["total_consideration"] == 157500.00, (
            f"total_consideration should be 157500.00, got {deal['total_consideration']}")
        assert deal["total_commission"] == 9450.00, (
            f"total_commission should be 9450.00, got {deal['total_commission']}")
        splits = get_commission_splits_for_deal(ctx)
        assert split_by_side(splits, "PROCURING")["amount"] == 3149.69, (
            "procuring = round(9450 * 0.3333) = 3149.69")
        assert split_by_side(splits, "LISTING")["amount"] == 6300.31, (
            "listing = residual 9450.00 - 3149.69 = 6300.31 (NOT independently rounded to 6300.32)")

    def test_consideration_sum_then_round_drives_commission(self, api):
        """PRD §3.7: "Sum every year's dollar contribution and round the single total half
        up to two decimal places — one rounding, after the full sum."
        PRD §3.8: "The deal's `total_commission` is then `total_consideration` multiplied by that
        effective rate, rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/commission_residual_rounding_order
        """
        # consideration 157,500.00 (sum-then-round) * 0.06 = 9,450.00 feeds the split.
        ctx = setup_executed_deal(
            co_broke=True, base_rent_psf_yr=26.25, term_months=24, annual_escalation_pct=0,
            rentable_sf=3000, asking_rent_psf_yr=26.25, co_broke_offered_pct=0.3333,
            default_commission_pct=0.06, max_rent_psf_yr=40, suite_no="901")
        deal = get_success_data(api.get_deal(ctx["deal"]["id"], make_listing_broker_headers(ctx["lb"]["id"])))
        assert deal["total_consideration"] == 157500.00
        assert deal["total_commission"] == 9450.00
        splits = get_commission_splits_for_deal(ctx)
        assert_commission_conserves_total(splits, 9450.00)

    def test_lease_consideration_escalated_stream(self, api):
        """PRD §3.7: "Sum every year's dollar contribution and round the single total
        half up to two decimal places — one rounding, after the full sum."

        Design: Corner/calculations/lease_consideration_escalated_stream_correct
        """
        ctx = setup_executed_deal(
            co_broke=True, base_rent_psf_yr=55, term_months=60, annual_escalation_pct=0.03,
            rentable_sf=5000, asking_rent_psf_yr=55, default_commission_pct=0.06)
        deal = get_success_data(api.get_deal(ctx["deal"]["id"], make_listing_broker_headers(ctx["lb"]["id"])))
        assert deal["total_consideration"] == 1460012.35, (
            f"total_consideration should be 1460012.35, got {deal['total_consideration']}")
        assert deal["total_commission"] == 87600.74, (
            f"total_commission should be 87600.74, got {deal['total_commission']}")

    def test_commission_rate_floored_at_minimum(self, api):
        """PRD §3.8: "The resulting rate is then floored so it never falls below 0.03
        (three percent): the effective rate is the larger of the discounted rate and
        0.03."

        Design: Corner/calculations/commission_floor_applied_long_term
        """
        # default 0.035 with a 120-month term would discount to 0.025, but the floor
        # raises it back to 0.03; consideration 2,000,000 * 0.03 = 60,000.00.
        ctx = setup_executed_deal(
            co_broke=False, base_rent_psf_yr=40, term_months=120, annual_escalation_pct=0,
            rentable_sf=5000, asking_rent_psf_yr=40, default_commission_pct=0.035)
        deal = get_success_data(api.get_deal(ctx["deal"]["id"], make_listing_broker_headers(ctx["lb"]["id"])))
        assert deal["total_consideration"] == 2000000.00, (
            f"total_consideration should be 2000000.00, got {deal['total_consideration']}")
        assert deal["total_commission"] == 60000.00, (
            f"floored commission should be 60000.00, got {deal['total_commission']}")
