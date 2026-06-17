"""Deal lifecycle: the cyclic re-quote loop, unit-hold cascades, and the
cross-entity preconditions that gate quote/approve/deliver transitions.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_customer_payload, create_unit_payload, create_trade_in_payload,
    create_deal_payload, TEST_USERS,
    create_customer, create_unit, create_in_stock_unit, setup_draft_deal,
)

SM = TEST_USERS["sales_manager_headers"]
FM = TEST_USERS["finance_manager_headers"]


def test_decline_then_requote_returns_to_quoted(api):
    """PRD 3.3: "The same quote action is reused to re-quote a DECLINED deal: a
    deal may move from DECLINED back to QUOTED, which again requires the unit to be
    IN_STOCK (else ERR_UNIT_NOT_AVAILABLE), again places the unit ON_HOLD under
    this deal, and again recomputes the figures with the provisional variant."

    Design: Difficulty/non_linear_state_machine/deal_decline_requote_cycle
    """
    cust, unit, deal = setup_draft_deal(sale_price_cents=1_400_000, tax_rate_bps=800,
                                        unit_overrides={"category": "MOTORCYCLE"})
    validate_success(api.quote_deal(deal["id"], SM), 200)
    validate_success(api.submit_finance_deal(deal["id"], FM), 200)
    validate_success(api.decline_deal(deal["id"], FM), 200)
    requoted = validate_success(api.quote_deal(deal["id"], SM), 200)
    assert requoted["status"] == "QUOTED"


def test_requote_reholds_unit(api):
    """PRD 3.3: "a deal may move from DECLINED back to QUOTED, which again requires
    the unit to be IN_STOCK (else ERR_UNIT_NOT_AVAILABLE), again places the unit
    ON_HOLD under this deal, and again recomputes the figures with the provisional
    variant."

    Design: Difficulty/non_linear_state_machine/deal_decline_requote_cycle
    """
    cust, unit, deal = setup_draft_deal(unit_overrides={"category": "MOTORCYCLE"})
    validate_success(api.quote_deal(deal["id"], SM), 200)
    validate_success(api.submit_finance_deal(deal["id"], FM), 200)
    validate_success(api.decline_deal(deal["id"], FM), 200)
    validate_success(api.quote_deal(deal["id"], SM), 200)
    unit_after = validate_success(api.get_unit(unit["id"], SM), 200)
    assert unit_after["status"] == "ON_HOLD"
    assert unit_after["held_by_deal_id"] == deal["id"]


def test_requote_rejected_when_unit_held_by_other_deal(api):
    """PRD 3.3: "a deal may move from DECLINED back to QUOTED, which again requires
    the unit to be IN_STOCK (else ERR_UNIT_NOT_AVAILABLE), again places the unit
    ON_HOLD under this deal, and again recomputes the figures with the provisional
    variant."

    Design: Difficulty/cross_entity_state_dependency/deal_requote_requires_unit_in_stock_held_elsewhere
    """
    cust = create_customer()
    unit = create_in_stock_unit(category="MOTORCYCLE")
    deal1 = validate_success(api.create_deal(
        create_deal_payload(cust["id"], unit["id"], sale_price_cents=1_500_000,
                            tax_rate_bps=800), SM), 201)
    validate_success(api.quote_deal(deal1["id"], SM), 200)
    validate_success(api.submit_finance_deal(deal1["id"], FM), 200)
    validate_success(api.decline_deal(deal1["id"], FM), 200)
    deal2 = validate_success(api.create_deal(
        create_deal_payload(cust["id"], unit["id"], sale_price_cents=1_500_000,
                            tax_rate_bps=800), SM), 201)
    validate_success(api.quote_deal(deal2["id"], SM), 200)

    res = api.quote_deal(deal1["id"], SM)
    validate_error(res, "ERR_UNIT_NOT_AVAILABLE")
    unit_after = validate_success(api.get_unit(unit["id"], SM), 200)
    assert unit_after["held_by_deal_id"] == deal2["id"]


def test_requote_blocked_leaves_first_deal_declined(api):
    """PRD 3.3: "a deal may move from DECLINED back to QUOTED, which again requires
    the unit to be IN_STOCK (else ERR_UNIT_NOT_AVAILABLE), again places the unit
    ON_HOLD under this deal, and again recomputes the figures with the provisional
    variant."

    Design: Difficulty/cross_entity_state_dependency/deal_requote_requires_unit_in_stock_held_elsewhere
    """
    cust = create_customer()
    unit = create_in_stock_unit(category="MOTORCYCLE")
    deal1 = validate_success(api.create_deal(
        create_deal_payload(cust["id"], unit["id"], sale_price_cents=1_500_000,
                            tax_rate_bps=800), SM), 201)
    validate_success(api.quote_deal(deal1["id"], SM), 200)
    validate_success(api.submit_finance_deal(deal1["id"], FM), 200)
    validate_success(api.decline_deal(deal1["id"], FM), 200)
    deal2 = validate_success(api.create_deal(
        create_deal_payload(cust["id"], unit["id"], sale_price_cents=1_500_000,
                            tax_rate_bps=800), SM), 201)
    validate_success(api.quote_deal(deal2["id"], SM), 200)

    res = api.quote_deal(deal1["id"], SM)
    validate_error(res, "ERR_UNIT_NOT_AVAILABLE")
    # The rejected re-quote must not advance deal1 out of DECLINED.
    deal1_after = validate_success(api.get_deal(deal1["id"], SM), 200)
    assert deal1_after["status"] == "DECLINED"


def test_quote_in_transit_unit_rejected(api):
    """PRD 3.3: "The referenced unit must be IN_STOCK, otherwise the quote is
    rejected with ERR_UNIT_NOT_AVAILABLE."

    Design: Corner/cross_cutting_complexity_layers/quote_in_transit_unit_rejected
    """
    cust = create_customer()
    unit = create_unit(category="MOTORCYCLE")  # never received -> IN_TRANSIT
    deal = validate_success(api.create_deal(
        create_deal_payload(cust["id"], unit["id"], sale_price_cents=1_400_000,
                            tax_rate_bps=800), SM), 201)
    res = api.quote_deal(deal["id"], SM)
    validate_error(res, "ERR_UNIT_NOT_AVAILABLE")
    unit_after = validate_success(api.get_unit(unit["id"], SM), 200)
    assert unit_after["status"] == "IN_TRANSIT"


def test_quote_holds_unit_cascade(api):
    """PRD 3.3: "A successful quote moves the unit from IN_STOCK to ON_HOLD and
    stamps held_by_deal_id with this deal's id, and computes the deal's financial
    figures using the provisional variant described in Section 3.4."

    Design: Corner/cross_cutting_complexity_layers/deal_quote_holds_unit_cascade
    """
    cust, unit, deal = setup_draft_deal(unit_overrides={"category": "MOTORCYCLE"})
    validate_success(api.quote_deal(deal["id"], SM), 200)
    unit_after = validate_success(api.get_unit(unit["id"], SM), 200)
    assert unit_after["status"] == "ON_HOLD"
    assert unit_after["held_by_deal_id"] == deal["id"]


def test_approve_deal_from_draft_rejected(api):
    """PRD 2.8: "any transition attempted from a state that is not a legal
    predecessor is rejected, and where a more specific state error is not named for
    that transition the generic ERR_INVALID_STATE (HTTP 409) is returned."
    PRD 3.3: "From FINANCE_SUBMITTED, the finance manager may approve or decline."

    Design: Corner/state_machines/approve_deal_from_draft_returns_invalid_state
    """
    cust, unit, deal = setup_draft_deal(unit_overrides={"category": "MOTORCYCLE"})
    res = api.approve_deal(deal["id"], FM)
    validate_error(res, "ERR_INVALID_STATE")
    deal_after = validate_success(api.get_deal(deal["id"], SM), 200)
    assert deal_after["status"] == "DRAFT"


def test_deliver_already_delivered_deal_rejected(api):
    """PRD 3.3: "the deal's status progresses through DRAFT, QUOTED,
    FINANCE_SUBMITTED, APPROVED, DELIVERED, with the side branches DECLINED and
    CANCELLED; DELIVERED and CANCELLED are terminal."
    PRD 2.8: "any transition attempted from a state that is not a legal predecessor
    is rejected, and where a more specific state error is not named for that
    transition the generic ERR_INVALID_STATE (HTTP 409) is returned."

    Design: Corner/state_machines/deliver_terminal_deal_idempotency_rejected
    """
    from test_helpers import setup_delivered_unit
    cust, unit, deal = setup_delivered_unit(clock="2026-06-01T00:00:00.000Z")
    res = api.deliver_deal(deal["id"], SM)
    validate_error(res, "ERR_INVALID_STATE")
    deal_after = validate_success(api.get_deal(deal["id"], SM), 200)
    assert deal_after["status"] == "DELIVERED"


def test_quote_with_rejected_trade_rejected(api):
    """PRD 3.3: "if a trade_in_id is present, that trade must be in APPRAISED
    status, otherwise the quote is rejected with ERR_TRADE_NOT_APPRAISED."

    Design: Corner/state_machines/trade_reject_then_quote_rejected_invalid_state
    """
    cust = create_customer()
    unit = create_in_stock_unit(category="MOTORCYCLE")
    trade = validate_success(api.create_trade_in(
        create_trade_in_payload(cust["id"], category="ATV",
                                appraised_value_cents=500_000,
                                estimated_payoff_cents=0), SM), 201)
    validate_success(api.reject_trade_in(trade["id"], SM), 200)
    deal = validate_success(api.create_deal(
        create_deal_payload(cust["id"], unit["id"], trade_in_id=trade["id"],
                            sale_price_cents=1_400_000, tax_rate_bps=800), SM), 201)
    res = api.quote_deal(deal["id"], SM)
    validate_error(res, "ERR_TRADE_NOT_APPRAISED")
