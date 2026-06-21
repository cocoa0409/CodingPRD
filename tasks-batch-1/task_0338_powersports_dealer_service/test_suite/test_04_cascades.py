"""Multi-hop cascades triggered by delivering a deal: the floor-plan payoff chain
and the trade titling chain that mints a new inventory unit.
"""
from test_helpers import (
    api_client, validate_success,
    create_deal_payload, create_trade_in_payload, create_floor_plan_loan_payload,
    create_unit_payload, TEST_USERS,
    create_customer, create_in_stock_unit, set_clock,
)

SM = TEST_USERS["sales_manager_headers"]
FM = TEST_USERS["finance_manager_headers"]
DP = TEST_USERS["dealer_principal_headers"]


def _deliver_floored_deal(api, dealer_cost_cents=1_000_000, sale_price_cents=1_500_000):
    set_clock("2026-06-01T00:00:00.000Z")
    cust = create_customer()
    raw = validate_success(api.create_unit(
        create_unit_payload(category="MOTORCYCLE", dealer_cost_cents=dealer_cost_cents,
                            acquisition_kind="NEW_FLOORED"), SM), 201)
    unit = validate_success(api.receive_unit(raw["id"], SM), 200)
    loan = validate_success(api.create_floor_plan_loan(
        create_floor_plan_loan_payload(unit["id"], opened_on="2026-06-01T00:00:00.000Z",
                                       apr_bps=900), DP), 201)
    deal = validate_success(api.create_deal(
        create_deal_payload(cust["id"], unit["id"], sale_price_cents=sale_price_cents,
                            tax_rate_bps=800), SM), 201)
    validate_success(api.quote_deal(deal["id"], SM), 200)
    validate_success(api.submit_finance_deal(deal["id"], FM), 200)
    validate_success(api.approve_deal(deal["id"], FM), 200)
    delivered = validate_success(api.deliver_deal(deal["id"], SM), 200)
    return unit, loan, delivered


def test_deliver_cascades_unit_to_delivered(api):
    """PRD 3.3: "Delivery drives a chain of cascades: the unit advances from SOLD
    to the terminal DELIVERED; if that unit has a floor_plan_loan_id, a SALE_PAYOFF
    curtailment for the loan's full principal_outstanding_cents is posted and the
    loan is driven to PAID_OFF."

    Design: Difficulty/transitive_cascade/deal_deliver_cascades_unit_then_floorplan_payoff_depth3
    """
    unit, loan, delivered = _deliver_floored_deal(api)
    assert delivered["status"] == "DELIVERED"
    unit_after = validate_success(api.get_unit(unit["id"], SM), 200)
    assert unit_after["status"] == "DELIVERED"


def test_deliver_cascades_floorplan_to_paid_off(api):
    """PRD 3.3: "if that unit has a floor_plan_loan_id, a SALE_PAYOFF curtailment
    for the loan's full principal_outstanding_cents is posted and the loan is
    driven to PAID_OFF."
    PRD 3.2: "A successful full payoff — whether posted directly with reason
    SALE_PAYOFF or generated as a cascade when a unit is delivered — drives the
    loan from either OPEN or CURTAILMENT_DUE to the terminal PAID_OFF status and
    sets principal_outstanding_cents to zero."

    Design: Difficulty/transitive_cascade/deal_deliver_cascades_unit_then_floorplan_payoff_depth3
    """
    unit, loan, delivered = _deliver_floored_deal(api)
    loan_after = validate_success(api.get_floor_plan_loan(loan["id"], DP), 200)
    assert loan_after["status"] == "PAID_OFF"
    assert loan_after["principal_outstanding_cents"] == 0


def _deliver_trade_deal(api):
    cust = create_customer()
    unit = create_in_stock_unit(category="UTV", msrp_cents=2_000_000,
                                dealer_cost_cents=1_500_000)
    trade = validate_success(api.create_trade_in(
        create_trade_in_payload(cust["id"], category="ATV",
                                appraised_value_cents=600_000,
                                estimated_payoff_cents=100_000), SM), 201)
    deal = validate_success(api.create_deal(
        create_deal_payload(cust["id"], unit["id"], trade_in_id=trade["id"],
                            sale_price_cents=2_000_000, tax_rate_bps=800,
                            approved_lender_payoff_cents=100_000), SM), 201)
    validate_success(api.quote_deal(deal["id"], SM), 200)
    validate_success(api.submit_finance_deal(deal["id"], FM), 200)
    validate_success(api.approve_deal(deal["id"], FM), 200)
    validate_success(api.deliver_deal(deal["id"], SM), 200)
    return cust, unit, trade


def test_deliver_with_trade_titles_trade(api):
    """PRD 3.3: "if the deal carries a trade, that trade advances from ACCEPTED to
    the terminal TITLED, which in turn mints a new inventory unit as described in
    Section 3.5."

    Design: Difficulty/transitive_cascade/deal_deliver_with_trade_cascades_titled_then_mints_unit_depth2
    """
    cust, unit, trade = _deliver_trade_deal(api)
    trade_after = validate_success(api.get_trade_in(trade["id"], SM), 200)
    assert trade_after["status"] == "TITLED"
    assert trade_after["resulting_unit_id"] is not None


def test_deliver_with_trade_mints_inventory_unit(api):
    """PRD 3.5: "Titling a trade mints a new Unit into inventory: the new unit is
    created with acquisition_kind of TRADE_IN, status IN_STOCK, and
    dealer_cost_cents set equal to the trade's appraised_value_cents."
    PRD 3.5: "The id of that minted unit is written back onto the trade's
    resulting_unit_id; until titling occurs, resulting_unit_id is null."

    Design: Difficulty/transitive_cascade/deal_deliver_with_trade_cascades_titled_then_mints_unit_depth2
    """
    cust, unit, trade = _deliver_trade_deal(api)
    trade_after = validate_success(api.get_trade_in(trade["id"], SM), 200)
    minted = validate_success(api.get_unit(trade_after["resulting_unit_id"], SM), 200)
    assert minted["acquisition_kind"] == "TRADE_IN"
    assert minted["status"] == "IN_STOCK"
    assert minted["dealer_cost_cents"] == 600_000
