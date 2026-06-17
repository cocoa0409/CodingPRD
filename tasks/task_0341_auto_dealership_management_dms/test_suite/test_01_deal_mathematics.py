"""Deal pricing mathematics: dual-variant payment/payoff and combinatorial
amount-financed, tax, and finance-reserve calculations.

Difficulty queue (A) instances: dual_variant_calc, combinatorial_formula.
"""
from test_helpers import (
    api_client, get_success_data, validate_success,
    TEST_USERS, fixtures,
)
from test_helpers import factories as f

INV = TEST_USERS["inventory_clerk_headers"]
SALES = TEST_USERS["sales_manager_headers"]
FIN = TEST_USERS["finance_manager_headers"]


def _build_d1_approved():
    """Build the canonical 'D1' deal through APPROVED with the rich pricing inputs
    shared by several dual-variant / combinatorial instances:
    sale 3200000, accessories 129500, doc 59900, title 7500, reg 35000, tax 725,
    cash_down 200000, trade allowance 900000 / payoff 600000, rebate 150000,
    products VSC 240000 + GAP 89500.
    Returns (deal_id, lender_program_id, approved_version).
    """
    veh = fixtures.create_vehicle(
        condition="NEW", make="ACME", model="SED", model_year=2026,
        msrp_cents=3300000, list_price_cents=3200000,
    )
    fixtures.floor_vehicle(veh["id"], veh["version"],
                           principal_cents=3000000, annual_rate_bps=825,
                           floored_on="2026-05-01T00:00:00.000Z")
    cust = fixtures.create_customer(credit_tier="TIER_A", drivers_license_valid=True,
                                    monthly_income_cents=2500000)
    lp = fixtures.create_lender_program(
        tier="TIER_A", buy_rate_bps=549, max_markup_bps=200,
        max_ltv_bps=12500, max_pti_bps=1800, max_term_months=72, active=True,
    )
    deal = fixtures.create_deal(
        veh["id"], cust["id"], deal_type="FINANCE",
        sale_price_cents=3200000, accessories_cents=129500, doc_fee_cents=59900,
        title_fee_cents=7500, registration_fee_cents=35000, tax_rate_bps=725,
        cash_down_cents=200000,
    )
    deal_id = deal["id"]
    get_success_data(api_client.attach_trade_in(
        deal_id, f.create_trade_in_payload(acv_cents=900000, allowance_cents=900000, payoff_cents=600000), SALES))
    inc = fixtures.create_oem_incentive(rebate_cents=150000, eligible_condition="ANY",
                                        eligible_make=None, min_model_year=None,
                                        stackable_with_finance=True, active=True)
    get_success_data(api_client.apply_incentive(deal_id, {"oem_incentive_id": inc["id"]}, SALES))
    fp_vsc = fixtures.create_finance_product(cost_cents=180000, max_retail_cents=300000, taxable=False)
    fp_gap = fixtures.create_finance_product(cost_cents=50000, max_retail_cents=120000, taxable=False)
    get_success_data(api_client.attach_product(deal_id, {"finance_product_id": fp_vsc["id"], "sold_price_cents": 240000}, FIN))
    get_success_data(api_client.attach_product(deal_id, {"finance_product_id": fp_gap["id"], "sold_price_cents": 89500}, FIN))
    get_success_data(api_client.desk_deal(deal_id, SALES))
    fixtures.upload_document(deal_id, "CREDIT_APP")
    get_success_data(api_client.submit_to_lender(deal_id, SALES))
    approved = get_success_data(
        api_client.lender_decision(deal_id, {"decision": "APPROVE", "lender_program_id": lp["id"]}, FIN))
    return deal_id, lp["id"], approved["version"]


# ===========================================================================
# dual_variant_calc / dual_variant_payment_estimate_vs_final
# ===========================================================================
class TestDualVariantPayment:
    def test_desk_estimate_payment_uses_provisional_rate_and_term(self, api):
        """PRD §3.4: "The ESTIMATE variant runs at every desk before any lender
        approval: it uses a provisional desking sell rate of 699 basis points
        (6.99%) and a provisional term of 72 months, and writes the result into
        the deal's `estimated_payment_cents`."

        Design: Difficulty/dual_variant_calc/dual_variant_payment_estimate_vs_final
        """
        veh = fixtures.create_vehicle(msrp_cents=3300000, list_price_cents=3200000)
        fixtures.floor_vehicle(veh["id"], veh["version"], principal_cents=3000000,
                               annual_rate_bps=825, floored_on="2026-05-01T00:00:00.000Z")
        cust = fixtures.create_customer(credit_tier="TIER_A", monthly_income_cents=2500000)
        deal = fixtures.create_deal(
            veh["id"], cust["id"], deal_type="FINANCE",
            sale_price_cents=3200000, accessories_cents=129500, doc_fee_cents=59900,
            title_fee_cents=7500, registration_fee_cents=35000, tax_rate_bps=725,
            cash_down_cents=200000,
        )
        deal_id = deal["id"]
        get_success_data(api.attach_trade_in(
            deal_id, f.create_trade_in_payload(acv_cents=900000, allowance_cents=900000, payoff_cents=600000), SALES))
        inc = fixtures.create_oem_incentive(rebate_cents=150000)
        get_success_data(api.apply_incentive(deal_id, {"oem_incentive_id": inc["id"]}, SALES))
        fp_vsc = fixtures.create_finance_product(cost_cents=180000, max_retail_cents=300000)
        fp_gap = fixtures.create_finance_product(cost_cents=50000, max_retail_cents=120000)
        get_success_data(api.attach_product(deal_id, {"finance_product_id": fp_vsc["id"], "sold_price_cents": 240000}, FIN))
        get_success_data(api.attach_product(deal_id, {"finance_product_id": fp_gap["id"], "sold_price_cents": 89500}, FIN))

        desked = validate_success(api.desk_deal(deal_id, SALES))
        assert desked["estimated_payment_cents"] == 56108, \
            f"estimate payment at 699bps/72mo on af 3291882, got {desked['estimated_payment_cents']}"

    def test_final_contract_payment_differs_from_desk_estimate(self, api):
        """PRD §3.4: "The FINAL variant runs when a finance contract is created
        after lender approval: it uses the contract's sell rate (the lender
        program's `buy_rate_bps` plus the contract's `markup_bps`) and the
        contract's `term_months`, and writes the result into the contract's
        `monthly_payment_cents`."

        Design: Difficulty/dual_variant_calc/dual_variant_payment_estimate_vs_final
        """
        deal_id, lp_id, approved_version = _build_d1_approved()
        deal = get_success_data(api.get_deal(deal_id, FIN))
        est = deal["estimated_payment_cents"]
        fc = validate_success(api.create_finance_contract(
            deal_id, f.create_finance_contract_payload(lp_id, approved_version, markup_bps=200, term_months=72), FIN),
            expected_status=201)
        assert fc["monthly_payment_cents"] == 56901, \
            f"FINAL payment at 749bps/72mo on af 3291882, got {fc['monthly_payment_cents']}"
        assert fc["monthly_payment_cents"] != est, \
            "FINAL payment must differ from the desking ESTIMATE (same af, different rate)"


# ===========================================================================
# dual_variant_calc / dual_variant_floor_plan_payoff_estimate_vs_actual
# ===========================================================================
class TestDualVariantPayoff:
    def _floored_line(self):
        veh = fixtures.create_vehicle(model="SUV", msrp_cents=4000000, list_price_cents=3800000)
        line = fixtures.floor_vehicle(veh["id"], veh["version"], principal_cents=3000000,
                                      annual_rate_bps=825, floored_on="2026-05-01T00:00:00.000Z")
        return line["id"]

    def test_payoff_quote_forward_estimate_date(self, api):
        """PRD §3.1: "The payoff is the current `principal_outstanding_cents`
        plus accrued interest, where the interest is the outstanding principal
        multiplied by the annual rate (the `annual_rate_bps` divided by ten
        thousand), divided by a 360-day year, multiplied by the number of days
        accrued, with the resulting interest rounded half up to whole cents."

        Design: Difficulty/dual_variant_calc/dual_variant_floor_plan_payoff_estimate_vs_actual
        """
        line_id = self._floored_line()
        quote = validate_success(api.payoff_quote(line_id, {"as_of_date": "2026-05-20T00:00:00.000Z"}, FIN))
        assert quote["days_accrued"] == 19, quote["days_accrued"]
        assert quote["interest_cents"] == 13063, quote["interest_cents"]
        assert quote["payoff_cents"] == 3013063, quote["payoff_cents"]

    def test_payoff_quote_actual_date_differs(self, api):
        """PRD §3.1: "The same line quoted as of two different dates yields two
        different payoffs because the day count differs."

        Design: Difficulty/dual_variant_calc/dual_variant_floor_plan_payoff_estimate_vs_actual
        """
        line_id = self._floored_line()
        est = validate_success(api.payoff_quote(line_id, {"as_of_date": "2026-05-20T00:00:00.000Z"}, FIN))
        act = validate_success(api.payoff_quote(line_id, {"as_of_date": "2026-05-25T00:00:00.000Z"}, FIN))
        assert act["days_accrued"] == 24, act["days_accrued"]
        assert act["interest_cents"] == 16500, act["interest_cents"]
        assert act["payoff_cents"] == 3016500, act["payoff_cents"]
        assert est["payoff_cents"] != act["payoff_cents"]


# ===========================================================================
# combinatorial_formula / combinatorial_amount_financed_multi_input_nonlinear
# ===========================================================================
class TestCombinatorialAmountFinanced:
    def _build_d2_desked(self):
        veh = fixtures.create_vehicle(msrp_cents=3300000, list_price_cents=3200000)
        cust = fixtures.create_customer(credit_tier="TIER_A", monthly_income_cents=2500000)
        deal = fixtures.create_deal(
            veh["id"], cust["id"], deal_type="FINANCE",
            sale_price_cents=3200000, accessories_cents=129500, doc_fee_cents=59900,
            title_fee_cents=7500, registration_fee_cents=35000, tax_rate_bps=725,
            cash_down_cents=200000,
        )
        deal_id = deal["id"]
        get_success_data(api_client.attach_trade_in(
            deal_id, f.create_trade_in_payload(acv_cents=900000, allowance_cents=900000, payoff_cents=600000), SALES))
        inc = fixtures.create_oem_incentive(rebate_cents=150000)
        get_success_data(api_client.apply_incentive(deal_id, {"oem_incentive_id": inc["id"]}, SALES))
        fp_vsc = fixtures.create_finance_product(cost_cents=180000, max_retail_cents=300000)
        fp_gap = fixtures.create_finance_product(cost_cents=50000, max_retail_cents=120000)
        get_success_data(api_client.attach_product(deal_id, {"finance_product_id": fp_vsc["id"], "sold_price_cents": 240000}, FIN))
        get_success_data(api_client.attach_product(deal_id, {"finance_product_id": fp_gap["id"], "sold_price_cents": 89500}, FIN))
        return deal_id

    def test_amount_financed_combines_all_inputs(self, api):
        """PRD §3.4: "The gross amount due is the sum of `sale_price_cents`,
        `accessories_cents`, `doc_fee_cents`, `title_fee_cents`,
        `registration_fee_cents`, the `total_tax_cents` just computed, and
        `fi_products_total_cents` (the sum of `sold_price_cents` over ACTIVE
        product lines on the deal). From that gross, three reductions are
        subtracted: the deal's `rebate_cents`, its `trade_equity_cents`, and its
        `cash_down_cents`. The result is `amount_financed_cents`."

        Design: Difficulty/combinatorial_formula/combinatorial_amount_financed_multi_input_nonlinear
        """
        deal_id = self._build_d2_desked()
        desked = validate_success(api.desk_deal(deal_id, SALES))
        assert desked["total_tax_cents"] == 180482, desked["total_tax_cents"]
        assert desked["trade_equity_cents"] == 300000, desked["trade_equity_cents"]
        assert desked["fi_products_total_cents"] == 329500, desked["fi_products_total_cents"]
        assert desked["amount_financed_cents"] == 3291882, desked["amount_financed_cents"]

    def test_amount_financed_visible_immediately_on_desk(self, api):
        """PRD §3.3: "Each desk recomputes the full quote: the deal's taxes,
        amount financed, front and back gross, and the provisional estimated
        monthly payment (all of these calculations are detailed in §3.4)."

        Design: Difficulty/combinatorial_formula/combinatorial_amount_financed_multi_input_nonlinear
        """
        deal_id = self._build_d2_desked()
        desked = validate_success(api.desk_deal(deal_id, SALES))
        # Re-reading the deal returns the same computed amount financed.
        fetched = validate_success(api.get_deal(deal_id, FIN))
        assert fetched["amount_financed_cents"] == 3291882 == desked["amount_financed_cents"]


# ===========================================================================
# combinatorial_formula / combinatorial_deal_tax_round_per_line_then_sum
# ===========================================================================
class TestCombinatorialTaxRounding:
    def _build_dr_desked(self):
        veh = fixtures.create_vehicle(condition="USED", model="CPE", model_year=2024,
                                      msrp_cents=2400000, list_price_cents=2200000)
        cust = fixtures.create_customer(credit_tier="TIER_B", monthly_income_cents=1800000)
        deal = fixtures.create_deal(
            veh["id"], cust["id"], deal_type="FINANCE",
            sale_price_cents=1899500, accessories_cents=129500, doc_fee_cents=59900,
            title_fee_cents=7500, registration_fee_cents=35000, tax_rate_bps=725,
            cash_down_cents=0,
        )
        return deal["id"]

    def test_tax_rounds_each_line_before_summing(self, api):
        """PRD §3.4: "Each of these three lines is multiplied by the rate and
        rounded half up to a whole cent **independently**, and only then are the
        three rounded line taxes added together to form `total_tax_cents`. This
        per-line-then-sum order is authoritative and must not be replaced by
        summing the bases and rounding once."

        Design: Difficulty/combinatorial_formula/combinatorial_deal_tax_round_per_line_then_sum
        """
        deal_id = self._build_dr_desked()
        desked = validate_success(api.desk_deal(deal_id, SALES))
        assert desked["total_tax_cents"] == 151446, \
            f"round-per-line tax should be 151446 (sum-then-round would give 151445), got {desked['total_tax_cents']}"

    def test_amount_financed_uses_round_per_line_tax(self, api):
        """PRD §3.4: "The gross amount due is the sum of `sale_price_cents`,
        `accessories_cents`, `doc_fee_cents`, `title_fee_cents`,
        `registration_fee_cents`, the `total_tax_cents` just computed, and
        `fi_products_total_cents` (the sum of `sold_price_cents` over ACTIVE
        product lines on the deal). From that gross, three reductions are
        subtracted: the deal's `rebate_cents`, its `trade_equity_cents`, and its
        `cash_down_cents`. The result is `amount_financed_cents`."

        Design: Difficulty/combinatorial_formula/combinatorial_deal_tax_round_per_line_then_sum
        """
        deal_id = self._build_dr_desked()
        desked = validate_success(api.desk_deal(deal_id, SALES))
        assert desked["amount_financed_cents"] == 2282846, desked["amount_financed_cents"]


# ===========================================================================
# combinatorial_formula / combinatorial_finance_reserve_pinned_eval_order
# ===========================================================================
class TestCombinatorialFinanceReserve:
    def test_finance_reserve_pinned_three_step_order(self, api):
        """PRD §3.4: "First, the effective markup is the smaller of the contract's
        `markup_bps` and the lender program's `max_markup_bps`. Second, the
        reserve rate is chosen by tier: if the effective markup is at most 150
        basis points, the reserve rate is one percent (0.01); if it is greater
        than 150 basis points, the reserve rate is two percent (0.02). Third,
        `finance_reserve_cents` is the snapshotted amount financed multiplied by
        the chosen reserve rate, rounded half up to whole cents."

        Design: Difficulty/combinatorial_formula/combinatorial_finance_reserve_pinned_eval_order
        """
        deal_id, lp_id, approved_version = _build_d1_approved()
        fc = validate_success(api.create_finance_contract(
            deal_id, f.create_finance_contract_payload(lp_id, approved_version, markup_bps=200, term_months=72), FIN),
            expected_status=201)
        assert fc["finance_reserve_cents"] == 65838, \
            f"effective markup 200 > 150 -> HIGH 0.02 on af 3291882, got {fc['finance_reserve_cents']}"

    def test_finance_contract_sell_rate_is_buy_plus_markup(self, api):
        """PRD §3.5: "Creating a finance contract snapshots the deal's current
        amount financed into `amount_financed_snapshot_cents`, computes
        `sell_rate_bps` as the program's buy rate plus the contract markup,
        computes the FINAL monthly payment and the finance reserve as specified
        in §3.4, and opens the contract in status `ACTIVE`."

        Design: Difficulty/combinatorial_formula/combinatorial_finance_reserve_pinned_eval_order
        """
        deal_id, lp_id, approved_version = _build_d1_approved()
        fc = validate_success(api.create_finance_contract(
            deal_id, f.create_finance_contract_payload(lp_id, approved_version, markup_bps=200, term_months=72), FIN),
            expected_status=201)
        assert fc["sell_rate_bps"] == 749, f"buy 549 + markup 200, got {fc['sell_rate_bps']}"
