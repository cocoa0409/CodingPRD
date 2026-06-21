"""Curtailment/tax/trade-equity calculations and business-rule validations.

Corner queue (B) sections: calculations, validations.
"""
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    ApiErrorId, TEST_USERS, fixtures,
)
from test_helpers import factories as f

INV = TEST_USERS["inventory_clerk_headers"]
SALES = TEST_USERS["sales_manager_headers"]
FIN = TEST_USERS["finance_manager_headers"]


# ===========================================================================
# calculations
# ===========================================================================
class TestCurtailment:
    def _floored_line(self, principal_cents=3000000):
        veh = fixtures.create_vehicle(model="SUV", msrp_cents=4000000, list_price_cents=3800000)
        line = fixtures.floor_vehicle(veh["id"], veh["version"], principal_cents=principal_cents,
                                      annual_rate_bps=825, floored_on="2026-05-01T00:00:00.000Z")
        return line["id"]

    def test_curtailment_due_at_exactly_90_days(self, api):
        """PRD §3.1: "A curtailment is due only when the age in days is at least
        90 days — the comparison is inclusive of exactly 90."
        PRD §3.1: "the reduction is ten percent of the original `principal_cents`,
        rounded half up to whole cents; that reduction is subtracted from
        `principal_outstanding_cents`, `curtailments_applied` increases by one".

        Design: Corner/calculations/curtailment_due_at_exactly_90_days
        """
        line_id = self._floored_line(3000000)
        # floored 2026-05-01, as_of 2026-07-30 == exactly 90 whole days.
        line = validate_success(api.create_curtailment(line_id, {"as_of_date": "2026-07-30T00:00:00.000Z"}, INV))
        assert line["principal_outstanding_cents"] == 2700000, line["principal_outstanding_cents"]
        assert line["curtailments_applied"] == 1, line["curtailments_applied"]

    def test_curtailment_not_due_at_89_days(self, api):
        """PRD §3.1: "If the line is younger than 90 days, the request is rejected
        with `ERR_CURTAILMENT_NOT_DUE`."

        Design: Corner/calculations/curtailment_not_due_at_89_days
        """
        line_id = self._floored_line(3000000)
        # as_of 2026-07-29 == 89 whole days < 90.
        resp = api.create_curtailment(line_id, {"as_of_date": "2026-07-29T00:00:00.000Z"}, INV)
        validate_error(resp, ApiErrorId.ERR_CURTAILMENT_NOT_DUE.value)


class TestTradeEquityAndTax:
    def test_negative_trade_equity_increases_amount_financed(self, api):
        """PRD §3.4: "Because `trade_equity_cents` is the trade allowance less the
        trade payoff, a trade with negative equity (payoff exceeding allowance) is
        itself negative and therefore increases the amount financed rather than
        reducing it."

        Design: Corner/calculations/negative_trade_equity_increases_amount_financed
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_A", monthly_income_cents=2500000)
        deal = fixtures.create_deal(veh["id"], cust["id"], deal_type="FINANCE",
                                    sale_price_cents=2000000, tax_rate_bps=725)
        deal_id = deal["id"]
        td = get_success_data(api.attach_trade_in(deal_id, f.create_trade_in_payload(
            acv_cents=800000, allowance_cents=800000, payoff_cents=1100000), SALES))
        assert td["gross_equity_cents"] == -300000, td["gross_equity_cents"]
        desked = validate_success(api.desk_deal(deal_id, SALES))
        assert desked["trade_equity_cents"] == -300000, desked["trade_equity_cents"]
        # taxable sale base = 2000000 - allowance 800000 = 1200000; tax @725bps = 87000.
        # gross due = sale 2000000 + tax 87000 = 2087000; reductions = trade_equity -300000.
        # amount financed = 2087000 - (-300000) = 2387000.
        assert desked["amount_financed_cents"] == 2387000, desked["amount_financed_cents"]

    def test_trade_allowance_reduces_taxable_base(self, api):
        """PRD §3.4: "The taxable sale base is the `sale_price_cents` reduced by
        the deal's `trade_allowance_cents` (the allowance is a tax credit),
        floored at zero so a large trade allowance never produces a negative
        base."

        Design: Corner/calculations/trade_allowance_reduces_taxable_base
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_A", monthly_income_cents=2500000)
        deal = fixtures.create_deal(veh["id"], cust["id"], deal_type="FINANCE",
                                    sale_price_cents=2000000, tax_rate_bps=725)
        deal_id = deal["id"]
        get_success_data(api.attach_trade_in(deal_id, f.create_trade_in_payload(
            acv_cents=900000, allowance_cents=900000, payoff_cents=0), SALES))
        desked = validate_success(api.desk_deal(deal_id, SALES))
        assert desked["trade_allowance_cents"] == 900000, desked["trade_allowance_cents"]
        # taxable sale base 2000000 - 900000 = 1100000; tax at 725 bps = 79750.
        assert desked["total_tax_cents"] == 79750, desked["total_tax_cents"]


# ===========================================================================
# validations
# ===========================================================================
class TestBusinessValidations:
    def test_product_price_exceeds_max_returns_409(self, api):
        """PRD §3.3: "the `sold_price_cents` must not exceed that product's
        `max_retail_cents`, otherwise the attach is rejected with
        `ERR_PRODUCT_PRICE_EXCEEDS_MAX`."

        Design: Corner/validations/product_price_exceeds_max_returns_409
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_A")
        fp = fixtures.create_finance_product(cost_cents=120000, max_retail_cents=250000)
        deal = fixtures.create_deal(veh["id"], cust["id"], deal_type="FINANCE",
                                    sale_price_cents=2000000, tax_rate_bps=725)
        resp = api.attach_product(deal["id"], {"finance_product_id": fp["id"], "sold_price_cents": 300000}, FIN)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_PRICE_EXCEEDS_MAX.value)

    def test_markup_exceeds_lender_max_returns_409(self, api):
        """PRD §3.5: "the markup must not exceed the lender program's
        `max_markup_bps` and the term must not exceed its `max_term_months`, or
        the create is rejected with `ERR_MARKUP_EXCEEDS_MAX`."

        Design: Corner/validations/markup_exceeds_lender_max_returns_409
        """
        ctx = fixtures.create_approved_deal(
            lender_overrides=dict(max_markup_bps=200),
            deal_overrides=dict(sale_price_cents=2000000, tax_rate_bps=725))
        resp = api.create_finance_contract(
            ctx["deal_id"],
            f.create_finance_contract_payload(ctx["lender_program_id"], ctx["deal"]["version"],
                                              markup_bps=300, term_months=72), FIN)
        validate_error(resp, ApiErrorId.ERR_MARKUP_EXCEEDS_MAX.value)

    def test_lender_tier_mismatch_on_approve_returns_409(self, api):
        """PRD §3.5: "the request names a `lender_program_id`, and the referenced
        lender program must have `active` equal to true and a `tier` matching the
        customer's `credit_tier`, or the decision is rejected with
        `ERR_LENDER_TIER_MISMATCH`."

        Design: Corner/validations/lender_tier_mismatch_on_approve_returns_409
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_A", monthly_income_cents=2500000)
        lp_b = fixtures.create_lender_program(tier="TIER_B", buy_rate_bps=799, max_markup_bps=200,
                                              max_ltv_bps=12500, max_pti_bps=1800, max_term_months=72)
        deal = fixtures.create_deal(veh["id"], cust["id"], deal_type="FINANCE",
                                    sale_price_cents=2000000, tax_rate_bps=725)
        deal_id = deal["id"]
        get_success_data(api.desk_deal(deal_id, SALES))
        fixtures.upload_document(deal_id, "CREDIT_APP")
        get_success_data(api.submit_to_lender(deal_id, SALES))
        resp = api.lender_decision(deal_id, {"decision": "APPROVE", "lender_program_id": lp_b["id"]}, FIN)
        validate_error(resp, ApiErrorId.ERR_LENDER_TIER_MISMATCH.value)

    def test_submit_to_lender_cash_deal_returns_409(self, api):
        """PRD §3.5: "Submission is gated twice: the deal's `deal_type` must be
        `FINANCE`, or the request is rejected with `ERR_DEAL_TYPE_NOT_FINANCE`".

        Design: Corner/validations/submit_to_lender_cash_deal_returns_409
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_A")
        deal = fixtures.create_deal(veh["id"], cust["id"], deal_type="CASH",
                                    sale_price_cents=2000000, tax_rate_bps=725)
        deal_id = deal["id"]
        get_success_data(api.desk_deal(deal_id, SALES))
        fixtures.upload_document(deal_id, "CREDIT_APP")
        resp = api.submit_to_lender(deal_id, SALES)
        validate_error(resp, ApiErrorId.ERR_DEAL_TYPE_NOT_FINANCE.value)

    def test_submit_to_lender_missing_credit_app_returns_409(self, api):
        """PRD §3.5: "and a deal-jacket document of type `CREDIT_APP` must already
        exist for the deal, or it is rejected with `ERR_CREDIT_APP_MISSING`."

        Design: Corner/validations/submit_to_lender_missing_credit_app_returns_409
        """
        veh = fixtures.create_vehicle(msrp_cents=2200000, list_price_cents=2000000)
        cust = fixtures.create_customer(credit_tier="TIER_A")
        deal = fixtures.create_deal(veh["id"], cust["id"], deal_type="FINANCE",
                                    sale_price_cents=2000000, tax_rate_bps=725)
        deal_id = deal["id"]
        get_success_data(api.desk_deal(deal_id, SALES))
        resp = api.submit_to_lender(deal_id, SALES)
        validate_error(resp, ApiErrorId.ERR_CREDIT_APP_MISSING.value)

    def test_contract_missing_active_contract_returns_409(self, api):
        """PRD §3.5: "an ACTIVE finance contract must exist on the deal, or
        `ERR_NO_ACTIVE_CONTRACT`".

        Design: Corner/validations/contract_missing_active_contract_returns_409
        """
        ctx = fixtures.create_approved_deal(deal_overrides=dict(sale_price_cents=2000000, tax_rate_bps=725))
        fixtures.upload_document(ctx["deal_id"], "INSURANCE")
        resp = api.contract_deal(ctx["deal_id"], FIN)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_CONTRACT.value)

    def test_contract_missing_insurance_stip_returns_409(self, api):
        """PRD §3.5: "and a deal-jacket document of type `INSURANCE` must exist
        for the deal, or `ERR_STIP_MISSING`."

        Design: Corner/validations/contract_missing_insurance_stip_returns_409
        """
        ctx = fixtures.create_approved_deal(deal_overrides=dict(sale_price_cents=2000000, tax_rate_bps=725))
        fixtures.add_finance_contract(ctx["deal_id"], ctx["lender_program_id"], ctx["deal"]["version"],
                                      markup_bps=100, term_months=72)
        resp = api.contract_deal(ctx["deal_id"], FIN)
        validate_error(resp, ApiErrorId.ERR_STIP_MISSING.value)

    def test_pti_exceeded_on_fund_returns_409(self, api):
        """PRD §3.6: "The payment-to-income cap must hold: the finance contract's
        `monthly_payment_cents` must not exceed the lender program's
        `max_pti_bps` divided by ten thousand, multiplied by the customer's
        `monthly_income_cents`, or funding is rejected with `ERR_PTI_EXCEEDED`."

        Design: Corner/validations/pti_exceeded_on_fund_returns_409
        """
        # CONTRACTED deal on a list_price-2000000 vehicle (LTV ok) with a very
        # low income customer so PTI fails at fund.
        ctx = fixtures.create_contracted_deal(
            deal_overrides=dict(sale_price_cents=2000000, tax_rate_bps=725),
            customer_overrides=dict(monthly_income_cents=150000),
            with_floor_plan=True, floor_overrides=dict(principal_cents=1800000),
            markup_bps=100, term_months=72)
        veh = get_success_data(api.get_vehicle(ctx["vehicle_id"], FIN))
        resp = api.fund_deal(ctx["deal_id"], {"expected_vehicle_version": veh["version"]}, FIN)
        validate_error(resp, ApiErrorId.ERR_PTI_EXCEEDED.value)
