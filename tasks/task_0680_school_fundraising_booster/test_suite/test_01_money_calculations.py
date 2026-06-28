"""Monetary calculations: forecast vs final views, order tax rounding, and the
profit-split reconciliation waterfall.

Covers difficulty queue A rules: dual_variant_calc, combinatorial_formula.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_active_catalog, setup_active_pledge,
    place_simple_order, place_and_pay_order, place_order, order_line,
    create_recorded_pledge, create_collected_pledge, create_pledge,
    close_campaign, reconcile_campaign,
    add_product,
    assert_campaign, assert_seller, assert_order,
    TEST_USERS,
)

ADMIN = TEST_USERS["campaign_admin_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


# ─── dual_variant_calc / campaign_forecast_vs_final_gross_diverge ──────────

class TestCampaignForecastVsFinalGross:
    def test_final_gross_counts_only_settled_money(self, api, treasurer_headers):
        """PRD §3.8: "the **final** view is `gross_collected_cents`: the sum of
        `total_charged_cents` over orders that are `PAID`, plus the sum of
        `collected_cents` over pledges that are `COLLECTED`."

        Design: Difficulty/dual_variant_calc/campaign_forecast_vs_final_gross_diverge
        """
        camp, seller, product = setup_active_catalog()
        place_and_pay_order(camp["id"], seller["id"], product["id"], 5)   # PAID, total 10825
        place_simple_order(camp["id"], seller["id"], product["id"], 1)    # PENDING
        create_recorded_pledge(camp["id"], seller["id"], per_unit_cents=0,
                               units_recorded=0, flat_cents=3000)         # RECORDED, not collected

        fetched = validate_success(api.get_campaign(camp["id"], treasurer_headers), 200)
        assert_campaign(fetched)
        assert fetched["gross_collected_cents"] == 10825, \
            f"final gross must count only the PAID order, got {fetched['gross_collected_cents']}"

    def test_forecast_gross_adds_pending_orders_and_recorded_pledges(self, api, treasurer_headers):
        """PRD §3.8: "The **forecast** view is `forecast_gross_cents`, which is
        forward-looking and adds not-yet-settled commitments to the same
        skeleton: the sum of `total_charged_cents` over orders whose
        `payment_status` is `PENDING` or `PAID`, plus the sum of
        `pledged_amount_cents` over pledges whose status is `RECORDED` or
        `COLLECTED`."

        Design: Difficulty/dual_variant_calc/campaign_forecast_vs_final_gross_diverge
        """
        camp, seller, product = setup_active_catalog()
        place_and_pay_order(camp["id"], seller["id"], product["id"], 5)   # PAID, total 10825
        place_simple_order(camp["id"], seller["id"], product["id"], 1)    # PENDING, total 2165
        create_recorded_pledge(camp["id"], seller["id"], per_unit_cents=0,
                               units_recorded=0, flat_cents=3000)         # RECORDED 3000

        fetched = validate_success(api.get_campaign(camp["id"], treasurer_headers), 200)
        # forecast = sum(total over PENDING|PAID orders) + sum(pledged over RECORDED|COLLECTED)
        #   PAID o1 (5 units): gross 10000, tax round_half_up(825.0)=825, total 10825
        #   PENDING o2 (1 unit): gross 2000, tax round_half_up(165.0)=165, total 2165
        #   RECORDED pledge: pledged 3000
        # forecast = 10825 + 2165 + 3000 = 15990
        assert fetched["forecast_gross_cents"] == 15990, \
            f"forecast = 10825 + 2165 + 3000, got {fetched['forecast_gross_cents']}"
        assert fetched["forecast_gross_cents"] > fetched["gross_collected_cents"], \
            "forecast must strictly exceed final when an order is PENDING and a pledge RECORDED"


# ─── dual_variant_calc / seller_credited_vs_forecast_diverge ───────────────

class TestSellerCreditedVsForecast:
    def test_final_credited_counts_only_paid_and_collected(self, api, treasurer_headers):
        """PRD §3.6: "A seller's `credited_cents` is the settled money attributed
        to them: the sum of `total_charged_cents` over their orders that are
        `PAID`, plus the sum of `collected_cents` over their pledges that are
        `COLLECTED`."

        Design: Difficulty/dual_variant_calc/seller_credited_vs_forecast_diverge
        """
        camp, seller, product = setup_active_catalog()
        mug = add_product(camp["id"], sku="MUG", name="Mug",
                          unit_price_cents=1299, unit_cost_cents=500, stock_qty=100)
        pen = add_product(camp["id"], sku="PEN", name="Pen",
                          unit_price_cents=750, unit_cost_cents=200, stock_qty=100)
        place_and_pay_order(camp["id"], seller["id"], product["id"], 5)   # PAID 10825
        place_order(camp["id"], seller["id"],
                    [order_line(mug["id"], 3), order_line(pen["id"], 2)])  # PENDING 5842
        create_recorded_pledge(camp["id"], seller["id"], per_unit_cents=0,
                               units_recorded=0, flat_cents=3000)          # RECORDED 3000
        create_collected_pledge(camp["id"], seller["id"], per_unit_cents=0,
                                units_recorded=0, flat_cents=5000)         # COLLECTED 5000

        fetched = validate_success(api.get_seller(seller["id"], treasurer_headers), 200)
        assert_seller(fetched)
        assert fetched["credited_cents"] == 15825, \
            f"final credited = 10825 (PAID) + 5000 (COLLECTED), got {fetched['credited_cents']}"

    def test_credit_forecast_adds_pending_and_recorded(self, api, treasurer_headers):
        """PRD: "The forward-looking projection, `forecast_credited_cents`,
        answers"

        PRD: ": the sum of `total_charged_cents` over their orders whose
        `payment_status` is `PENDING` or `PAID`, plus the sum of
        `pledged_amount_cents` over their pledges whose status is `RECORDED`
        or `COLLECTED`."

        Design: Difficulty/dual_variant_calc/seller_credited_vs_forecast_diverge
        """
        camp, seller, product = setup_active_catalog()
        mug = add_product(camp["id"], sku="MUG", name="Mug",
                          unit_price_cents=1299, unit_cost_cents=500, stock_qty=100)
        pen = add_product(camp["id"], sku="PEN", name="Pen",
                          unit_price_cents=750, unit_cost_cents=200, stock_qty=100)
        place_and_pay_order(camp["id"], seller["id"], product["id"], 5)   # PAID 10825
        place_order(camp["id"], seller["id"],
                    [order_line(mug["id"], 3), order_line(pen["id"], 2)])  # PENDING 5842
        create_recorded_pledge(camp["id"], seller["id"], per_unit_cents=0,
                               units_recorded=0, flat_cents=3000)          # RECORDED 3000
        create_collected_pledge(camp["id"], seller["id"], per_unit_cents=0,
                                units_recorded=0, flat_cents=5000)         # COLLECTED 5000

        forecast = validate_success(
            api.get_seller_credit_forecast(seller["id"], treasurer_headers), 200)
        # PRD §3.8 names the forward-looking projection `forecast_credited_cents`
        # ("The forward-looking projection, `forecast_credited_cents`, answers
        # ...") — distinct from the final `credited_cents`. The credit-forecast
        # read is the "dedicated forecast read" that exposes it.
        # (10825 + 5842) orders + (3000 + 5000) pledges = 24667
        assert forecast["forecast_credited_cents"] == 24667, \
            f"forecast credited must add PENDING order + RECORDED pledge, got {forecast.get('forecast_credited_cents')}"


# ─── combinatorial_formula / order_tax_sum_then_round_not_round_then_sum ───

class TestOrderTaxSumThenRound:
    def test_tax_rounded_once_on_order_gross(self, api, admin_headers):
        """PRD §3.4: "`tax_cents` is then the campaign's sales tax applied once
        to the order-level `gross_cents` — that is, `gross_cents` multiplied by
        the tax rate of 0.0825, rounded half-up once to a whole number of cents —
        and never computed per line and summed, which could differ by a cent."

        Design: Difficulty/combinatorial_formula/order_tax_sum_then_round_not_round_then_sum
        """
        camp, seller, _ = setup_active_catalog()
        mug = add_product(camp["id"], sku="MUG", name="Mug",
                          unit_price_cents=1299, unit_cost_cents=500, stock_qty=50)
        pen = add_product(camp["id"], sku="PEN", name="Pen",
                          unit_price_cents=750, unit_cost_cents=200, stock_qty=50)
        order = place_order(camp["id"], seller["id"],
                            [order_line(mug["id"], 3), order_line(pen["id"], 2)])
        full = validate_success(api.get_order(order["id"], admin_headers), 200)
        assert_order(full)
        assert full["gross_cents"] == 5397, f"gross 1299*3 + 750*2, got {full['gross_cents']}"
        assert full["tax_cents"] == 445, \
            f"round_half_up(5397*0.0825)=445 (sum-then-round, not 446), got {full['tax_cents']}"

    def test_total_is_gross_plus_tax(self, api, admin_headers):
        """PRD §3.4: "`total_charged_cents` is `gross_cents` plus `tax_cents`. A
        newly placed order begins with `payment_status` `PENDING` and
        `fulfillment_status` `PLACED`, and its `receipt_number` is null."

        Design: Difficulty/combinatorial_formula/order_tax_sum_then_round_not_round_then_sum
        """
        camp, seller, _ = setup_active_catalog()
        mug = add_product(camp["id"], sku="MUG", name="Mug",
                          unit_price_cents=1299, unit_cost_cents=500, stock_qty=50)
        pen = add_product(camp["id"], sku="PEN", name="Pen",
                          unit_price_cents=750, unit_cost_cents=200, stock_qty=50)
        order = place_order(camp["id"], seller["id"],
                            [order_line(mug["id"], 3), order_line(pen["id"], 2)])
        full = validate_success(api.get_order(order["id"], admin_headers), 200)
        assert full["total_charged_cents"] == 5842, \
            f"5397 + 445 = 5842, got {full['total_charged_cents']}"


# ─── combinatorial_formula / profit_split_evaluation_order_pinned ──────────

class TestProfitSplitWaterfall:
    def _setup_reconcile_ready(self):
        """psp 0.60; one PAID 5-unit order @price2000/cost800 (gross 10000),
        one COLLECTED pledge of 5000. Returns (camp, post_close_version)."""
        camp, seller, product = setup_active_catalog(profit_split_pct=0.60)
        place_and_pay_order(camp["id"], seller["id"], product["id"], 5)
        create_collected_pledge(camp["id"], seller["id"], per_unit_cents=0,
                                units_recorded=0, flat_cents=5000)
        closed = close_campaign(camp["id"])
        return camp, closed["version"]

    def test_school_profit_is_split_pct_of_split_base(self, api):
        """PRD §3.7: "the waterfall pays the school first: `school_profit_cents`
        is the split base multiplied by the campaign's `profit_split_pct`,
        rounded half-up once to whole cents"

        Design: Difficulty/combinatorial_formula/profit_split_evaluation_order_pinned
        """
        camp, v_closed = self._setup_reconcile_ready()
        # split_base = (product_revenue 10000 - vendor_cogs 4000) + pledge_revenue 5000 = 11000
        # school_profit = round_half_up(11000 * 0.60) = 6600
        reconciled = validate_success(api.reconcile_campaign(
            camp["id"], {"expected_campaign_version": v_closed}, TREASURER), 200)
        assert reconciled["school_profit_cents"] == 6600, \
            f"round_half_up(11000*0.60)=6600, got {reconciled['school_profit_cents']}"
        assert reconciled["posture"] == "RECONCILED"

    def test_vendor_payable_is_cogs_plus_residual(self, api):
        """PRD §3.7: "`vendor_payable_cents` is the vendor cost of goods plus the
        exact residual of the split base after the school's profit is removed."

        Design: Difficulty/combinatorial_formula/profit_split_evaluation_order_pinned
        """
        camp, v_closed = self._setup_reconcile_ready()
        # vendor_payable = vendor_cogs 4000 + (split_base 11000 - school_profit 6600) = 8400
        reconciled = validate_success(api.reconcile_campaign(
            camp["id"], {"expected_campaign_version": v_closed}, TREASURER), 200)
        assert reconciled["vendor_payable_cents"] == 8400, \
            f"4000 + (11000 - 6600) = 8400, got {reconciled['vendor_payable_cents']}"
