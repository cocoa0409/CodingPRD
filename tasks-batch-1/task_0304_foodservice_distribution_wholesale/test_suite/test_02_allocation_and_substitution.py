"""Inventory allocation: substitution fallback and reservation cascade.

Covers corner calculations (substitute_fallback) and the depth-2 approve-credit cascade
from the difficulty queue (reservation + AR debit).
"""
from test_helpers import (
    api_client, validate_success,
    setup_catalog, setup_base, create_product, add_price_tier, receive_lot,
    create_customer, create_submitted_order, get_customer_version, approve_credit_payload,
    TEST_USERS,
)

CREDIT = TEST_USERS["credit_manager_headers"]
SALES = TEST_USERS["sales_rep_headers"]


def test_substitute_fallback_reprices_on_substitute_tiers(api):
    """PRD §3.4: "If a shortfall remains and the product carries a `substitute_product_id`,
    the system repeats the same first-expiry-first-out draw against the substitute
    product's lots at the same warehouse; if any substitute splits are taken, the line is
    marked `substituted` true."
    PRD §3.4: "Because a substituted line is fulfilled by a different product, it is priced
    on that substitute's tiers."
    PRD §3.4: "The line's `fulfilled_product_id` is set to the substitute product's id when
    the line was filled entirely from the substitute (the primary took nothing)."

    Primary A (out of stock) substitutes to B (spc 10, tier 900, 20 splits). A CASE-2 line
    (need 20) allocates fully from B: substituted=true, fulfilled_product_id=B, priced on
    B's tier -> 2 * 900 = 1800.

    Design: Corner/calculations/substitute_fallback_reprices_on_substitute_tiers
    """
    base = setup_base()
    dist_id = base["distributor"]["id"]
    wh_id = base["warehouse"]["id"]

    prod_b = create_product(dist_id, sku="B-1", name="Sub", category="DAIRY",
                            splits_per_case=10, case_cost_cents=800)
    add_price_tier(prod_b["id"], 1, 900)
    prod_a = create_product(dist_id, sku="A-1", name="Primary", category="DAIRY",
                            splits_per_case=10, substitute_product_id=prod_b["id"],
                            case_cost_cents=1000)
    add_price_tier(prod_a["id"], 1, 1000)
    receive_lot(prod_b["id"], wh_id, 20, lot_code="LB")
    cust = create_customer(dist_id, base["route"]["id"], credit_limit_cents=100000)

    order, lines = create_submitted_order(cust["id"], prod_a["id"],
                                          lines=[(prod_a["id"], "CASE", 2)])
    line = lines[0]

    cust_v = get_customer_version(cust["id"])
    validate_success(api.approve_credit(order["id"], approve_credit_payload(cust_v), CREDIT), 200)

    line_after = validate_success(api.get_order_line(line["id"], SALES), 200)
    assert line_after["substituted"] is True
    assert line_after["fulfilled_product_id"] == prod_b["id"]
    assert line_after["allocated_splits"] == 20
    assert line_after["unit_case_price_cents"] == 900
    assert line_after["extended_price_cents"] == 1800


def test_approve_credit_reserves_lot_and_debits_ar(api):
    """PRD §3.4: "increasing that lot's `reserved_splits` by the same amount."
    PRD §3.4: "the order's `credit_status` becomes `APPROVED` and the customer's
    `ar_balance_cents` is increased by `order_total_cents`."

    Approving a CASE-2 order (24 splits, total 4800) reserves the lot (reserved 0->24)
    and debits the customer AR by the order total (0->4800).

    Design: Difficulty/transitive_cascade/approve_credit_cascade_order_to_lots_depth2
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=24, credit_limit_cents=100000)
    lot = cat["lot"]
    order, lines = create_submitted_order(
        cat["customer"]["id"], cat["product"]["id"],
        lines=[(cat["product"]["id"], "CASE", 2)])

    cust_v = get_customer_version(cat["customer"]["id"])
    approved = validate_success(
        api.approve_credit(order["id"], approve_credit_payload(cust_v), CREDIT), 200)
    assert approved["order_total_cents"] == 4800

    lot_after = validate_success(api.get_inventory_lot(lot["id"], SALES), 200)
    assert lot_after["reserved_splits"] == 24

    cust_after = validate_success(api.get_customer(cat["customer"]["id"], SALES), 200)
    assert cust_after["ar_balance_cents"] == 4800


def test_approve_credit_reservation_and_ar_second_quantity(api):
    """PRD §3.4: "adding what it takes to the line's `allocated_splits`, increasing that
    lot's `reserved_splits` by the same amount."
    PRD §3.4: "the order's `credit_status` becomes `APPROVED` and the customer's
    `ar_balance_cents` is increased by `order_total_cents`."

    Second test of the depth-2 cascade with a different quantity: a CASE-1 order
    (12 splits, total 2400) reserves 12 and debits AR by 2400.

    Design: Difficulty/transitive_cascade/approve_credit_cascade_order_to_lots_depth2
    """
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=24, credit_limit_cents=100000)
    lot = cat["lot"]
    order, lines = create_submitted_order(
        cat["customer"]["id"], cat["product"]["id"],
        lines=[(cat["product"]["id"], "CASE", 1)])

    cust_v = get_customer_version(cat["customer"]["id"])
    approved = validate_success(
        api.approve_credit(order["id"], approve_credit_payload(cust_v), CREDIT), 200)
    assert approved["order_total_cents"] == 2400

    lot_after = validate_success(api.get_inventory_lot(lot["id"], SALES), 200)
    assert lot_after["reserved_splits"] == 12

    cust_after = validate_success(api.get_customer(cat["customer"]["id"], SALES), 200)
    assert cust_after["ar_balance_cents"] == 2400
