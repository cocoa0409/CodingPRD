"""Dividend declaration, pricing variants, reinvestment execution, tax report."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_shares_equal,
    create_active_plan,
    declare_dividend,
    deposit_shares,
    execute_dividend_at,
    get_dividend_event,
    get_enrollment,
    get_success_data,
    get_tax_report,
    list_ledger_entries,
    list_tax_lots,
    set_clock,
    setup_priced_dividend_scenario,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]


def _both_pricing_basis_legs():
    """Two ACTIVE plans identical except pricing_basis, each with an ACTIVE
    enrollment holding 100.0000 shares (@1500) and a PRICED dividend of
    50 cents/share (closing 2000, avg5 2100)."""
    plan_mc, _p_mc, e_mc, d_mc = setup_priced_dividend_scenario(
        plan_overrides={"issuer_name": "Acme Corp", "ticker": "ACME",
                        "name": "ACME DRIP MC", "pricing_basis": "MARKET_CLOSE"},
        participant_email="pa@x.com")
    plan_avg, _p_avg, e_avg, d_avg = setup_priced_dividend_scenario(
        plan_overrides={"issuer_name": "Beta Corp", "ticker": "BETA",
                        "name": "BETA DRIP AVG",
                        "pricing_basis": "FIVE_DAY_AVERAGE"},
        participant_email="pb@x.com")
    return (plan_mc, e_mc, d_mc), (plan_avg, e_avg, d_avg)


class TestReinvestmentPricingBasisVariants:
    def test_pricing_basis_selects_reference_price(self, api):
        """PRD §3.4: "the system selects between them according to the plan's
        `pricing_basis` — the closing price for `MARKET_CLOSE`, the five-day
        average for `FIVE_DAY_AVERAGE`."
        PRD §3.4: "The discounted reinvestment price is then the selected
        reference multiplied by one minus the plan's `discount_pct`, rounded
        half-up to whole cents, and stored as `reinvestment_price_cents`."

        Design: Difficulty/dual_variant_calc/reinvestment_price_market_close_vs_five_day_average
        """
        (plan_mc, _e_mc, d_mc), (plan_avg, _e_avg, d_avg) = \
            _both_pricing_basis_legs()
        priced_mc = get_dividend_event(plan_mc["id"], d_mc["id"])
        priced_avg = get_dividend_event(plan_avg["id"], d_avg["id"])
        assert priced_mc["reinvestment_price_cents"] == 1900, (
            "MARKET_CLOSE: round_half_up(2000 * 0.95) == 1900")
        assert priced_avg["reinvestment_price_cents"] == 1995, (
            "FIVE_DAY_AVERAGE: round_half_up(2100 * 0.95) == 1995")

    def test_pricing_basis_diverges_reinvested_shares(self, api):
        """PRD §3.4: "The two bases are genuinely divergent variants: identical
        dividend data yields a different `reinvestment_price_cents`, and
        therefore a different reinvested share count, under `FIVE_DAY_AVERAGE`
        than under `MARKET_CLOSE`."
        PRD §3.4: "The reinvested shares are the reinvested cash divided by the
        stored `reinvestment_price_cents`, rounded half-up to four decimal
        places."
        PRD §3.4: "Each reinvestment writes a `REINVEST` ledger entry (positive
        quantity at the reinvestment price, `DIVIDEND` provenance naming the
        dividend event) and a `REINVEST` tax lot whose `quantity` is the
        reinvested shares, whose `cost_per_share_cents` is the reinvestment
        price, and whose `total_basis_cents` is the actual cash reinvested —
        not the shares-times-price product."

        Design: Difficulty/dual_variant_calc/reinvestment_price_market_close_vs_five_day_average
        """
        (plan_mc, e_mc, d_mc), (plan_avg, e_avg, d_avg) = \
            _both_pricing_basis_legs()
        set_clock("2026-09-20T10:00:00Z")
        get_success_data(api.execute_dividend_event(d_mc["id"], ADMIN))
        get_success_data(api.execute_dividend_event(d_avg["id"], ADMIN))

        reinvest_mc = list_ledger_entries(e_mc["id"], entry_type="REINVEST")
        reinvest_avg = list_ledger_entries(e_avg["id"], entry_type="REINVEST")
        assert len(reinvest_mc) == 1 and len(reinvest_avg) == 1
        # FULL_REINVEST: 100.0000 eligible shares * 50 cents = 5000 cents reinvested.
        assert_shares_equal(reinvest_mc[0]["quantity"], "2.6316",
                            "5000 / 1900 rounded half-up to 4dp")
        assert_shares_equal(reinvest_avg[0]["quantity"], "2.5063",
                            "5000 / 1995 rounded half-up to 4dp")
        assert reinvest_mc[0]["quantity"] != reinvest_avg[0]["quantity"], \
            "identical inputs must diverge purely from pricing_basis"

        assert_shares_equal(get_enrollment(e_mc["id"])["share_balance"], "102.6316")
        assert_shares_equal(get_enrollment(e_avg["id"])["share_balance"], "102.5063")

        lots_mc = [l for l in list_tax_lots(e_mc["id"])
                   if l["acquisition_type"] == "REINVEST"]
        lots_avg = [l for l in list_tax_lots(e_avg["id"])
                    if l["acquisition_type"] == "REINVEST"]
        assert len(lots_mc) == 1 and len(lots_avg) == 1
        for lot in (lots_mc[0], lots_avg[0]):
            assert lot["total_basis_cents"] == 5000, \
                "the REINVEST lot basis is the actual cash reinvested"
        assert lots_mc[0]["cost_per_share_cents"] == 1900
        assert lots_avg[0]["cost_per_share_cents"] == 1995


class TestReinvestmentNestedRounding:
    def test_price_rounded_to_cents_before_share_division(self, api):
        """PRD §2.5: "First, a discounted reinvestment price is rounded half-up
        to whole cents before any share division takes place."
        PRD §3.4: "The reinvested shares are the reinvested cash divided by the
        stored `reinvestment_price_cents`, rounded half-up to four decimal
        places."

        Design: Difficulty/combinatorial_formula/reinvestment_nested_rounding_order_pinned
        """
        _plan, _participant, enrollment, dividend = setup_priced_dividend_scenario(
            plan_overrides={"issuer_name": "Round Corp", "ticker": "RND",
                            "name": "RND DRIP"},
            closing_price_cents=1999, participant_email="pr@x.com")
        priced = get_dividend_event(_plan["id"], dividend["id"])
        assert priced["reinvestment_price_cents"] == 1899, (
            "round_half_up(1999 * 0.95) = round_half_up(1899.05) == 1899")

        execute_dividend_at(dividend["id"])
        reinvest = list_ledger_entries(enrollment["id"], entry_type="REINVEST")
        assert len(reinvest) == 1
        assert_shares_equal(reinvest[0]["quantity"], "2.6330", (
            "5000 / 1899 == 2.6330; dividing by the unrounded 1899.05 would "
            "yield 2.6329"))

    def test_nested_rounding_balance_and_lot(self, api):
        """PRD §2.5: "First, a discounted reinvestment price is rounded half-up
        to whole cents before any share division takes place."
        PRD §3.4: "a `REINVEST` tax lot whose `quantity` is the reinvested
        shares, whose `cost_per_share_cents` is the reinvestment price, and
        whose `total_basis_cents` is the actual cash reinvested — not the
        shares-times-price product."

        Design: Difficulty/combinatorial_formula/reinvestment_nested_rounding_order_pinned
        """
        plan, _participant, enrollment, dividend = setup_priced_dividend_scenario(
            plan_overrides={"issuer_name": "Round Corp", "ticker": "RND",
                            "name": "RND DRIP"},
            closing_price_cents=1999, participant_email="pr@x.com")
        execute_dividend_at(dividend["id"])
        assert_shares_equal(get_enrollment(enrollment["id"])["share_balance"],
                            "102.6330")
        lots = [l for l in list_tax_lots(enrollment["id"])
                if l["acquisition_type"] == "REINVEST"]
        assert len(lots) == 1
        assert_shares_equal(lots[0]["quantity"], "2.6330")
        assert lots[0]["cost_per_share_cents"] == 1899
        assert lots[0]["total_basis_cents"] == 5000


class TestDividendStateMachine:
    def test_dividend_execute_from_declared_rejected(self, api):
        """PRD §3.4: "Execution runs the reinvestment, moving the event from
        `PRICED` to `REINVESTED`."
        PRD §2.8: "Any state-machine trigger attempted from a state where it is
        not defined — including any action against an entity already in a
        terminal state, or repeating a transition already taken — is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/dividend_execute_from_declared_rejected
        """
        plan = create_active_plan(issuer_name="Div Corp", ticker="DIV",
                                  name="DIV DRIP")
        dividend = declare_dividend(plan["id"])
        resp = api.execute_dividend_event(dividend["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_dividend_event(plan["id"], dividend["id"])["status"] == "DECLARED"


class TestRecordDateEligibility:
    def test_dividend_record_date_cutoff_excludes_late_shares(self, api):
        """PRD §3.4: "Eligible shares are the sum of ledger entry quantities
        recorded at or before 23:59:59 UTC on the `record_date` — holders of
        record at the end of that date."
        PRD §3.4: "The total dividend cash is the eligible shares times
        `amount_per_share_cents`, rounded half-up to whole cents."

        Design: Corner/calculations/dividend_record_date_cutoff_excludes_late_shares
        """
        plan, participant, enrollment, dividend = setup_priced_dividend_scenario(
            plan_overrides={"issuer_name": "Cut Corp", "ticker": "CUT",
                            "name": "CUT DRIP"},
            participant_email="pcu@x.com")
        # setup's 100-share deposit ran at the startup clock (2026-08-01),
        # before the 2026-09-10 record date; now add 50 shares after it.
        set_clock("2026-09-15T00:00:00Z")
        deposit_shares(enrollment["id"], 50.0, 1500)

        execute_dividend_at(dividend["id"])
        reinvest = list_ledger_entries(enrollment["id"], entry_type="REINVEST")
        assert len(reinvest) == 1
        assert_shares_equal(reinvest[0]["quantity"], "2.6316", (
            "only the 100.0000 record-date-eligible shares earn the dividend: "
            "100 * 50 = 5000 cents reinvested at 1900"))
        assert_shares_equal(get_enrollment(enrollment["id"])["share_balance"],
                            "152.6316", (
                                "both deposits are in the balance; only the "
                                "first earned the dividend"))


class TestPartialReinvestSplit:
    def test_partial_reinvest_split_rounds_reinvest_first(self, api):
        """PRD §3.4: "That total is then split according to the enrollment's
        `election`: under `FULL_REINVEST` the entire total is reinvested and the
        cash payout is zero; under `CASH_ONLY` nothing is reinvested and the
        entire total pays out in cash; under `PARTIAL_REINVEST` the reinvested
        portion is the total times `reinvest_pct`, rounded half-up to whole
        cents first, and the cash payout is the remainder — so the two portions
        always sum exactly back to the total."
        PRD §3.4: "The cash portion writes a `CASH_PAYOUT` entry whose
        `quantity` is 0 and whose `cash_cents` is the full cash amount (the
        entire dividend when the election is `CASH_ONLY`)."

        Design: Corner/calculations/partial_reinvest_split_rounds_reinvest_first
        """
        plan, participant, enrollment, dividend = setup_priced_dividend_scenario(
            plan_overrides={"issuer_name": "Part Corp", "ticker": "PRT",
                            "name": "PRT DRIP"},
            election="PARTIAL_REINVEST", reinvest_pct=0.5,
            participant_email="ppr@x.com")
        execute_dividend_at(dividend["id"])

        reinvest = list_ledger_entries(enrollment["id"], entry_type="REINVEST")
        payout = list_ledger_entries(enrollment["id"], entry_type="CASH_PAYOUT")
        assert len(reinvest) == 1 and len(payout) == 1
        assert_shares_equal(reinvest[0]["quantity"], "1.3158",
                            "2500 reinvested / 1900 rounded half-up to 4dp")
        assert reinvest[0]["price_cents"] == 1900
        assert_shares_equal(payout[0]["quantity"], "0.0000")
        assert payout[0]["cash_cents"] == 2500
        # Split invariant: 2500 reinvested + 2500 paid out == 5000 total.
        assert 2500 + payout[0]["cash_cents"] == 5000
        assert_shares_equal(get_enrollment(enrollment["id"])["share_balance"],
                            "101.3158")


class TestTaxReportDividends:
    def test_tax_report_aggregates_declared_dividends(self, api):
        """PRD §3.9: "The annual tax report assembles these figures for a
        requested `year`, returning that `year`, the `dividends_cents` declared
        for the year, and the year's disposition totals — `proceeds_cents`,
        `basis_cents`, and `gain_cents` — computed under the plan's basis
        method, plus the `basis_method` in force."
        PRD §3.4: "under `CASH_ONLY` nothing is reinvested and the entire total
        pays out in cash"

        Design: Corner/calculations/tax_report_aggregates_declared_dividends
        """
        plan, participant, enrollment, dividend = setup_priced_dividend_scenario(
            plan_overrides={"issuer_name": "Tax Corp", "ticker": "TAX",
                            "name": "TAX DRIP"},
            election="CASH_ONLY", participant_email="ptx@x.com")
        execute_dividend_at(dividend["id"])

        payout = list_ledger_entries(enrollment["id"], entry_type="CASH_PAYOUT")
        assert len(payout) == 1 and payout[0]["cash_cents"] == 5000
        assert list_ledger_entries(enrollment["id"], entry_type="REINVEST") == []

        report = get_tax_report(enrollment["id"], 2026)
        assert report["year"] == 2026
        assert report["dividends_cents"] == 5000, \
            "the full declared dividend cash counts as dividends for the year"
        assert report["proceeds_cents"] == 0
        assert report["basis_cents"] == 0
        assert report["gain_cents"] == 0
        assert report["basis_method"] == "FIFO"
