"""Settlement side effects (receipt numbers, collected amount) and reservation
recomputation on delivery.

Covers corner queue B section: calculations.
"""
import pytest
from test_helpers import (
    validate_success,
    setup_active_catalog, setup_active_pledge,
    place_simple_order, place_and_pay_order, create_recorded_pledge,
    TEST_USERS,
)

ADMIN = TEST_USERS["campaign_admin_headers"]


def test_pledge_collect_sets_collected_and_receipt(api, admin_headers):
    """PRD §3.5: "On collection, `collected_cents` is set to the current
    `pledged_amount_cents` (the value left standing after any record-and-revise
    loop has settled), a sequential `receipt_number` is assigned, and the pledge
    now counts toward the seller's `credited_cents` and the campaign's
    `gross_collected_cents`; the seller's `earned_prize_tier_id` is recomputed
    and may cross a tier."

    Design: Corner/calculations/pledge_collect_sets_collected_and_receipt
    """
    camp, seller = setup_active_pledge()
    recorded = create_recorded_pledge(camp["id"], seller["id"],
                                      per_unit_cents=200, units_recorded=25)  # pledged 5000
    collected = validate_success(api.collect_pledge(recorded["id"], admin_headers), 200)
    assert collected["status"] == "COLLECTED"
    assert collected["collected_cents"] == 5000
    assert collected["receipt_number"] is not None, "collect assigns a receipt_number"


def test_order_pay_assigns_receipt_number(api, admin_headers):
    """PRD §3.4: "On payment the server assigns the order a sequential
    `receipt_number`"

    PRD §3.4: "A newly placed order begins with `payment_status` `PENDING` and
    `fulfillment_status` `PLACED`, and its `receipt_number` is null."

    Design: Corner/calculations/order_pay_assigns_receipt_number
    """
    camp, seller, product = setup_active_catalog()
    order = place_simple_order(camp["id"], seller["id"], product["id"], 2)
    assert order["receipt_number"] is None
    paid = validate_success(api.pay_order(order["id"], admin_headers), 200)
    assert paid["payment_status"] == "PAID"
    assert paid["receipt_number"] is not None, "pay assigns a non-null receipt_number"


def test_deliver_reduces_reserved_qty(api, admin_headers):
    """PRD §3.4: "on delivery the reservation is released into delivery so the
    delivered units leave the reserved pool and `reserved_qty` recomputes."

    Design: Corner/calculations/deliver_reduces_reserved_qty
    """
    camp, seller, product = setup_active_catalog(stock_qty=10)
    order = place_and_pay_order(camp["id"], seller["id"], product["id"], 4)
    validate_success(api.confirm_order(order["id"], admin_headers), 200)
    confirmed_prod = validate_success(api.get_product(product["id"], admin_headers), 200)
    assert confirmed_prod["reserved_qty"] == 4

    validate_success(api.deliver_order(order["id"], admin_headers), 200)
    after = validate_success(api.get_product(product["id"], admin_headers), 200)
    assert after["reserved_qty"] == 0, "delivered units leave the reserved pool"
