"""Calculation corner cases: grading fee for STANDARD tier, loyalty-tier promotion
at the inclusive SILVER threshold, and consignment settle crediting the consignor.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_customer, create_inventory_item, create_inventory_item_with_stock,
    create_open_event, create_registration, create_sold_consignment, set_clock,
    create_grading_submission_payload,
    TEST_USERS, make_customer_headers,
)

SM = TEST_USERS["store_manager_headers"]


def test_grading_fee_standard_tier(api):
    """PRD §3.6: "the base is 1500 cents; a value surcharge is the
    `declared_value_cents` multiplied by 100 basis points (1%, that is, divided by
    10000) and rounded half-up to whole cents; the sum of the base and the value
    surcharge is then multiplied by a service-tier multiplier — 1.0 for `ECONOMY`,
    1.5 for `STANDARD`, and 2.5 for `EXPRESS` — and the product is rounded half-up to
    whole cents and pinned as `grading_fee_cents`."

    Design: Corner/calculations/grading_fee_standard_tier_value
    """
    item, owner = create_inventory_item_with_stock(market_price_cents=9000, quantity=1)
    gs = get_success_data(api.create_grading_submission(
        create_grading_submission_payload(owner["id"], item["id"],
                                          declared_value_cents=10000,
                                          service_tier="STANDARD"), SM))
    sent = validate_success(api.send_grading_submission(gs["id"], SM), 200)
    # surcharge round(10000*0.01)=100; (1500+100)*1.5 = 2400
    assert sent["grading_fee_cents"] == 2400


def test_loyalty_tier_promotes_to_silver_at_threshold(api):
    """PRD §3.1: "a customer at or above 50000 cents is `SILVER`; otherwise the
    customer is `BRONZE`. The boundaries are inclusive — reaching a threshold exactly
    promotes the customer."
    PRD §3.1: "it is the sum of the negated `delta_cents` of only those ledger rows
    whose `reason` is `EVENT_CHARGE` or `PREORDER_FULFILL`"

    Design: Corner/calculations/loyalty_tier_silver_threshold_inclusive
    """
    set_clock("2026-06-01T00:00:00Z")
    cust = create_customer("Tier Cust", "tier@x.com", credit_cents=60000)
    ev = create_open_event(title="Pricey Event", format="STANDARD",
                           starts_at="2026-06-20T00:00:00Z",
                           ends_at="2026-06-20T04:00:00Z", capacity=8,
                           entry_fee_cents=50000)
    reg = create_registration(ev, cust)
    validate_success(api.pay_registration(reg["id"], make_customer_headers(cust["id"])), 200)
    cust_after = validate_success(api.get_customer(cust["id"], SM), 200)
    assert cust_after["lifetime_spend_cents"] == 50000
    assert cust_after["loyalty_tier"] == "SILVER"
    assert cust_after["store_credit_balance_cents"] == 10000


def test_consignment_settle_credits_consignor(api):
    """PRD §3.7: "Settling a sold case is a store-manager action defined only from
    `SOLD` (otherwise `ERR_INVALID_STATE`); it moves the case to `SETTLED`, appends a
    ledger row with `reason` `CONSIGNMENT_PAYOUT` and `delta_cents` equal to the
    positive `payout_total_cents`, and recomputes the customer's
    `store_credit_balance_cents`."

    Design: Corner/calculations/consignment_settle_credits_consignor
    """
    cust = create_customer("Settle Cust", "settle@x.com")
    item = create_inventory_item(title="Pricey Single", market_price_cents=10000)
    cc = create_sold_consignment(cust, item, quantity=1, ask_price_cents=10000,
                                 commission_rate_bps=1500)
    # commission round(10000*0.15)=1500; net 8500; total 8500
    assert cc["payout_total_cents"] == 8500
    settled = validate_success(api.settle_consignment_case(cc["id"], SM), 200)
    assert settled["status"] == "SETTLED"
    cust_after = validate_success(api.get_customer(cust["id"], SM), 200)
    assert cust_after["store_credit_balance_cents"] == 8500
