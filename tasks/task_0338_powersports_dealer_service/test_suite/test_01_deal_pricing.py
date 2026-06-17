"""Deal pricing: trade equity, out-the-door, and financed amount.

Covers the dual-variant financed-amount calculation, the per-line tax rounding
order on out-the-door, the doc-fee default, and immediate consistency of the
quote response.
"""
from test_helpers import (
    api_client, validate_success,
    create_customer_payload, create_unit_payload, create_trade_in_payload,
    create_deal_payload, TEST_USERS,
    create_in_stock_unit, create_customer, setup_draft_deal,
)

SM = TEST_USERS["sales_manager_headers"]
FM = TEST_USERS["finance_manager_headers"]


def test_amount_financed_provisional_vs_final_diverges(api):
    """PRD 3.4: "Under the provisional variant the payoff is the trade's
    estimated_payoff_cents; under the final variant the payoff is the deal's
    approved_lender_payoff_cents."
    PRD 3.4: "Because the provisional and final variants feed a different payoff
    into trade equity, an identical deal yields a different amount_financed_cents
    at quote than at approval whenever a trade is attached and the estimated and
    lender-confirmed payoffs differ."

    Design: Difficulty/dual_variant_calc/deal_amount_financed_provisional_vs_final_diverges
    """
    cust = create_customer(full_name="Pat Rider")
    unit_raw = validate_success(api.create_unit(
        create_unit_payload(category="MOTORCYCLE", msrp_cents=2_200_000,
                            dealer_cost_cents=1_700_000, acquisition_kind="NEW_FLOORED"), SM), 201)
    api.receive_unit(unit_raw["id"], SM)
    trade = validate_success(api.create_trade_in(
        create_trade_in_payload(cust["id"], category="MOTORCYCLE",
                                appraised_value_cents=800_000,
                                estimated_payoff_cents=500_000), SM), 201)
    deal = validate_success(api.create_deal(
        create_deal_payload(cust["id"], unit_raw["id"], trade_in_id=trade["id"],
                            sale_price_cents=2_000_000, freight_setup_cents=0,
                            tax_rate_bps=800, doc_fee_cents=39900,
                            down_payment_cents=100_000,
                            approved_lender_payoff_cents=650_000), SM), 201)

    quoted = validate_success(api.quote_deal(deal["id"], SM), 200)
    assert quoted["amount_financed_cents"] == 1_775_900, (
        f"provisional financed expected 1775900, got {quoted['amount_financed_cents']}")

    validate_success(api.submit_finance_deal(deal["id"], FM), 200)
    approved = validate_success(api.approve_deal(deal["id"], FM), 200)
    assert approved["status"] == "APPROVED"
    assert approved["amount_financed_cents"] == 1_937_900, (
        f"final financed expected 1937900, got {approved['amount_financed_cents']}")


def test_amount_financed_variant_divergence_documented(api):
    """PRD 3.4: "Because the provisional and final variants feed a different payoff
    into trade equity, an identical deal yields a different amount_financed_cents
    at quote than at approval whenever a trade is attached and the estimated and
    lender-confirmed payoffs differ."

    Design: Difficulty/dual_variant_calc/deal_amount_financed_provisional_vs_final_diverges
    """
    cust = create_customer()
    unit_raw = validate_success(api.create_unit(
        create_unit_payload(category="MOTORCYCLE", msrp_cents=2_200_000,
                            dealer_cost_cents=1_700_000, acquisition_kind="NEW_FLOORED"), SM), 201)
    api.receive_unit(unit_raw["id"], SM)
    trade = validate_success(api.create_trade_in(
        create_trade_in_payload(cust["id"], appraised_value_cents=800_000,
                                estimated_payoff_cents=500_000), SM), 201)
    deal = validate_success(api.create_deal(
        create_deal_payload(cust["id"], unit_raw["id"], trade_in_id=trade["id"],
                            sale_price_cents=2_000_000, freight_setup_cents=0,
                            tax_rate_bps=800, doc_fee_cents=39900,
                            down_payment_cents=100_000,
                            approved_lender_payoff_cents=650_000), SM), 201)
    quoted = validate_success(api.quote_deal(deal["id"], SM), 200)
    validate_success(api.submit_finance_deal(deal["id"], FM), 200)
    approved = validate_success(api.approve_deal(deal["id"], FM), 200)
    assert approved["amount_financed_cents"] != quoted["amount_financed_cents"], (
        "final financed must differ from provisional when payoffs differ")


def test_out_the_door_per_line_rounding_order_pinned(api):
    """PRD 3.4: "Tax on each line is that line's taxable base multiplied by
    tax_rate_bps, divided by 10000, then rounded half up; crucially, the two tax
    amounts are each rounded to whole cents before they are added, never summed
    as fractions and rounded once (see Section 2.5)."
    PRD 3.4: "The out-the-door price is then the sum of sale_price_cents,
    freight_setup_cents, the rounded tax on the sale line, the rounded tax on the
    freight line, and the documentation fee doc_fee_cents."

    Design: Difficulty/combinatorial_formula/deal_out_the_door_per_line_rounding_order_pinned
    """
    cust = create_customer(full_name="Lee Buyer")
    unit = create_in_stock_unit(category="UTV", msrp_cents=1_600_000,
                                dealer_cost_cents=1_200_000)
    deal = validate_success(api.create_deal(
        create_deal_payload(cust["id"], unit["id"], sale_price_cents=1_234_550,
                            freight_setup_cents=4575, tax_rate_bps=825,
                            doc_fee_cents=39900, down_payment_cents=0), SM), 201)
    quoted = validate_success(api.quote_deal(deal["id"], SM), 200)
    assert quoted["status"] == "QUOTED"
    assert quoted["out_the_door_cents"] == 1_381_252, (
        f"per-line-rounded OTD expected 1381252, got {quoted['out_the_door_cents']}")


def test_out_the_door_two_taxable_lines_present(api):
    """PRD 3.4: "The out-the-door price, out_the_door_cents, aggregates two
    independently taxable lines plus a non-taxable documentation fee."
    PRD 3.4: "The second taxable line is the freight-and-setup charge,
    freight_setup_cents, taxed in full as its own line."

    Design: Difficulty/combinatorial_formula/deal_out_the_door_per_line_rounding_order_pinned
    """
    cust = create_customer()
    unit = create_in_stock_unit(category="UTV")
    deal = validate_success(api.create_deal(
        create_deal_payload(cust["id"], unit["id"], sale_price_cents=1_234_550,
                            freight_setup_cents=4575, tax_rate_bps=825,
                            doc_fee_cents=39900, down_payment_cents=0), SM), 201)
    quoted = validate_success(api.quote_deal(deal["id"], SM), 200)
    # OTD includes both the freight base and the doc fee (non-taxable) on top of
    # the per-line rounded taxes; the pinned literal encodes that aggregation.
    assert quoted["out_the_door_cents"] == 1_381_252


def test_quote_response_is_immediately_consistent(api):
    """PRD 3.3: "A successful quote moves the unit from IN_STOCK to ON_HOLD and
    stamps held_by_deal_id with this deal's id, and computes the deal's financial
    figures using the provisional variant described in Section 3.4."

    Design: Corner/consistency_model/immediate_consistency_deal_quote_reflected_in_same_response
    """
    cust = create_customer(full_name="Imm Deal")
    unit = create_in_stock_unit(category="MOTORCYCLE", dealer_cost_cents=1_000_000)
    deal = validate_success(api.create_deal(
        create_deal_payload(cust["id"], unit["id"], sale_price_cents=1_000_000,
                            freight_setup_cents=0, tax_rate_bps=800,
                            doc_fee_cents=39900, down_payment_cents=0), SM), 201)
    quoted = validate_success(api.quote_deal(deal["id"], SM), 200)
    # OTD = 1000000 + 0 + round(1000000*0.08)=80000 + 0 + 39900 = 1119900
    assert quoted["out_the_door_cents"] == 1_119_900
    assert quoted["status"] == "QUOTED"


def test_doc_fee_default_applied_when_omitted(api):
    """PRD 3.3: "the doc_fee_cents defaults to 39900 (that is, $399.00)."

    Design: Corner/entities/deal_doc_fee_default_applied_when_omitted
    """
    cust = create_customer(full_name="Def Doc")
    unit = create_in_stock_unit(category="MOTORCYCLE", dealer_cost_cents=1_000_000)
    deal = validate_success(api.create_deal(
        {"customer_id": cust["id"], "unit_id": unit["id"],
         "sale_price_cents": 1_400_000, "tax_rate_bps": 800}, SM), 201)
    assert deal["doc_fee_cents"] == 39900
