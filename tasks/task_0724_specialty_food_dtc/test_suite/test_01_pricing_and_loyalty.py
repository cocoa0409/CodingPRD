"""Order pricing, loyalty accrual, renewal charge, and bulk-quote calculations.

Difficulty queue: dual_variant_calc, combinatorial_formula, boundary_precision_check.
Corner queue: calculations section + consistency_model.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_paginated, get_success_data,
    create_order_payload, create_order_line_payload, pay_order_payload,
    create_bulk_quote_payload,
    create_active_sku_with_lot, create_customer, create_corporate_buyer,
    build_reserved_order, build_shipped_order, setup_subscription_due_for_renewal,
    setup_draft_bulk_quote, set_clock,
    make_customer_headers, make_corporate_buyer_headers, TEST_USERS,
)

INV = TEST_USERS["inventory_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ───────────────────────── order_total combinatorial ─────────────────────────

def test_order_total_tiered_discount_with_capped_redemption(api):
    """PRD §3.6: "The redeemed_points actually applied is the smallest of three
    quantities: the buyer's requested_redeem_points, that redemption cap, and the
    customer's current loyalty_points_balance. Because one point is one cent, the
    final total_cents is the pre-redemption amount minus redeemed_points."
    PRD §3.6: "a subtotal of at least 5000 cents earns 5 percent"

    Design: Difficulty/combinatorial_formula/combinatorial_order_total_tiered_nonlinear
    """
    sku_a, _ = create_active_sku_with_lot(name="Reaper Sauce", category="HOT_SAUCE",
                                          storage_class="AMBIENT", unit_price_cents=2000,
                                          produced_units=100, lot_code="LA")
    sku_b, _ = create_active_sku_with_lot(name="Pepper Snack", category="SNACK",
                                          storage_class="AMBIENT", unit_price_cents=1800,
                                          produced_units=100, lot_code="LB")
    cust = create_customer(home_zone="Z2")
    cid = cust["id"]

    # Prior 8000-cent ambient order ships -> 120 loyalty points (8000*0.015=120).
    build_shipped_order(cid, [(sku_a["id"], 4)], ship_zone="Z1")
    cust_after = validate_success(api.get_customer(cid, make_customer_headers(cid)), 200)
    assert cust_after["loyalty_points_balance"] == 120, "prior shipped order grants 120 points"

    # Order under test: two ambient lines, subtotal 9600, zone Z2, request 120 points.
    order = get_success_data(api.create_order(
        create_order_payload(cid, order_kind="ONE_TIME", ship_zone="Z2",
                             requested_redeem_points=120), make_customer_headers(cid)))
    api.add_order_line(order["id"], create_order_line_payload(sku_a["id"], 3), make_customer_headers(cid))
    api.add_order_line(order["id"], create_order_line_payload(sku_b["id"], 2), make_customer_headers(cid))
    reserved = validate_success(api.reserve_order(order["id"], make_customer_headers(cid)), 200)

    assert reserved["subtotal_cents"] == 9600
    assert reserved["discount_cents"] == 480
    assert reserved["handling_cents"] == 0
    assert reserved["shipping_cents"] == 800
    assert reserved["redeemed_points"] == 120
    assert reserved["total_cents"] == 9800


def test_order_total_redemption_capped_at_30pct_of_discounted(api):
    """PRD §3.6: "The redemption cap is the floor of 0.30 times the discounted subtotal —
    loyalty may pay for at most 30 percent of the discounted merchandise value. The
    redeemed_points actually applied is the smallest of three quantities: the buyer's
    requested_redeem_points, that redemption cap, and the customer's current
    loyalty_points_balance."

    Design: Difficulty/combinatorial_formula/combinatorial_order_total_tiered_nonlinear
    """
    # Prior shipped ambient order: 1000 * 95 = 95000 -> round(95000*0.015) = 1425 points.
    sku, _ = create_active_sku_with_lot(name="Cap Sauce", category="HOT_SAUCE",
                                        storage_class="AMBIENT", unit_price_cents=1000,
                                        produced_units=200)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    build_shipped_order(cid, [(sku["id"], 95)], ship_zone="Z1")
    cust_after = validate_success(api.get_customer(cid, make_customer_headers(cid)), 200)
    assert cust_after["loyalty_points_balance"] == 1425

    # Order under test: subtotal 5000 (5% tier) -> discounted 4750 -> cap = floor(0.30*4750)=1425.
    # Request 2000 (> cap and > nothing); balance 1425 == cap, so the cap binds at 1425.
    order = get_success_data(api.create_order(
        create_order_payload(cid, order_kind="ONE_TIME", ship_zone="Z1",
                             requested_redeem_points=1425), make_customer_headers(cid)))
    api.add_order_line(order["id"], create_order_line_payload(sku["id"], 5), make_customer_headers(cid))
    reserved = validate_success(api.reserve_order(order["id"], make_customer_headers(cid)), 200)
    assert reserved["subtotal_cents"] == 5000
    assert reserved["discount_cents"] == 250
    assert reserved["redeemed_points"] == 1425, "min(requested 1425, cap 1425, balance 1425)"
    assert reserved["total_cents"] == 3825, "4750 + 0 handling + 500 Z1 ship - 1425 redeemed"


def test_order_total_5pct_tier_at_exactly_5000(api):
    """PRD §3.6: "a subtotal of at least 20000 cents earns 15 percent, at least 10000
    cents earns 10 percent, at least 5000 cents earns 5 percent, and below 5000 cents
    earns no discount. The discount_cents is that percentage of subtotal_cents, rounded
    half up"

    Design: Difficulty/boundary_precision_check/boundary_volume_discount_tier_5000
    """
    sku, _ = create_active_sku_with_lot(name="Edge Sauce", category="HOT_SAUCE",
                                        storage_class="AMBIENT", unit_price_cents=2500,
                                        produced_units=10)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    order = get_success_data(api.create_order(
        create_order_payload(cid, order_kind="ONE_TIME", ship_zone="Z1"),
        make_customer_headers(cid)))
    api.add_order_line(order["id"], create_order_line_payload(sku["id"], 2), make_customer_headers(cid))
    reserved = validate_success(api.reserve_order(order["id"], make_customer_headers(cid)), 200)

    assert reserved["subtotal_cents"] == 5000
    assert reserved["discount_cents"] == 250, "5% tier applies AT 5000 (>= boundary)"
    assert reserved["total_cents"] == 5250


def test_order_total_4999_below_5pct_boundary_no_discount(api):
    """PRD §3.6: "at least 5000 cents earns 5 percent, and below 5000 cents earns no discount."

    Design: Difficulty/boundary_precision_check/boundary_volume_discount_tier_5000
    """
    # 4999 subtotal: one unit at 2999 + one unit at 2000 -> 4999 < 5000 -> no discount.
    sku_a, _ = create_active_sku_with_lot(name="Edge A Sauce", category="HOT_SAUCE",
                                          storage_class="AMBIENT", unit_price_cents=2999,
                                          produced_units=10, lot_code="LEA")
    sku_b, _ = create_active_sku_with_lot(name="Edge B Sauce", category="HOT_SAUCE",
                                          storage_class="AMBIENT", unit_price_cents=2000,
                                          produced_units=10, lot_code="LEB")
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    order = get_success_data(api.create_order(
        create_order_payload(cid, order_kind="ONE_TIME", ship_zone="Z1"),
        make_customer_headers(cid)))
    api.add_order_line(order["id"], create_order_line_payload(sku_a["id"], 1), make_customer_headers(cid))
    api.add_order_line(order["id"], create_order_line_payload(sku_b["id"], 1), make_customer_headers(cid))
    reserved = validate_success(api.reserve_order(order["id"], make_customer_headers(cid)), 200)
    assert reserved["subtotal_cents"] == 4999
    assert reserved["discount_cents"] == 0, "below 5000 earns no discount"
    assert reserved["total_cents"] == 5499, "4999 + 0 disc + 0 handling + 500 Z1 ship"


def test_order_total_below_5000_no_discount(api):
    """PRD §3.6: "and below 5000 cents earns no discount."
    PRD §3.6: "the base shipping cost is keyed on the order's ship_zone: 500 cents for Z1"

    Design: Corner/consistency_model/immediate_reserve_total_visible_in_same_response
    """
    sku, _ = create_active_sku_with_lot(name="Imm Sauce", category="HOT_SAUCE",
                                        storage_class="AMBIENT", unit_price_cents=1200,
                                        produced_units=5)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    order = get_success_data(api.create_order(
        create_order_payload(cid, order_kind="ONE_TIME", ship_zone="Z1"),
        make_customer_headers(cid)))
    api.add_order_line(order["id"], create_order_line_payload(sku["id"], 3), make_customer_headers(cid))
    # The reserve response itself must carry the computed total (immediate consistency).
    reserved = validate_success(api.reserve_order(order["id"], make_customer_headers(cid)), 200)
    assert reserved["total_cents"] == 4100, "3600 subtotal + 0 disc + 0 handling + 500 Z1 ship"


def test_perishable_order_handling_and_expedited_shipping(api):
    """PRD §3.6: "The handling_cents is a perishable cold-pack surcharge of 450 cents for
    each line whose SKU is PERISHABLE"
    PRD §3.6: "If the order has at least one perishable line, shipping_cents is that zone
    base multiplied by 1.5, rounded half up; otherwise shipping_cents is exactly the zone base."

    Design: Corner/calculations/perishable_order_total_handling_and_expedite
    """
    sku_p, _ = create_active_sku_with_lot(name="Cold Brew", category="COFFEE",
                                          storage_class="PERISHABLE", unit_price_cents=1500,
                                          produced_units=50, lot_code="LP")
    sku_a, _ = create_active_sku_with_lot(name="Amb Sauce", category="HOT_SAUCE",
                                          storage_class="AMBIENT", unit_price_cents=1200,
                                          produced_units=50, lot_code="LA")
    cust = create_customer(home_zone="Z3")
    cid = cust["id"]
    order = get_success_data(api.create_order(
        create_order_payload(cid, order_kind="ONE_TIME", ship_zone="Z3"),
        make_customer_headers(cid)))
    api.add_order_line(order["id"], create_order_line_payload(sku_p["id"], 4), make_customer_headers(cid))
    api.add_order_line(order["id"], create_order_line_payload(sku_a["id"], 3), make_customer_headers(cid))
    reserved = validate_success(api.reserve_order(order["id"], make_customer_headers(cid)), 200)

    assert reserved["subtotal_cents"] == 9600
    assert reserved["discount_cents"] == 480
    assert reserved["handling_cents"] == 450
    assert reserved["shipping_cents"] == 1800, "Z3 base 1200 * 1.5"
    assert reserved["total_cents"] == 11370


# ───────────────────────── loyalty accrual rounding order ─────────────────────────

def test_loyalty_accrual_rounds_per_line_then_sums(api):
    """PRD §3.7: "The accrual rounds per line and then sums — for each ambient line the
    system computes that line's unit_price_cents times its quantity times 0.015 and rounds
    the result half up, and only then adds the rounded per-line figures together."

    Design: Difficulty/combinatorial_formula/combinatorial_loyalty_accrual_rounding_order
    """
    sku, _ = create_active_sku_with_lot(name="Mini Sauce", category="HOT_SAUCE",
                                        storage_class="AMBIENT", unit_price_cents=350,
                                        produced_units=10)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    order = get_success_data(api.create_order(
        create_order_payload(cid, order_kind="ONE_TIME", ship_zone="Z1"),
        make_customer_headers(cid)))
    api.add_order_line(order["id"], create_order_line_payload(sku["id"], 1), make_customer_headers(cid))
    api.add_order_line(order["id"], create_order_line_payload(sku["id"], 1), make_customer_headers(cid))
    api.reserve_order(order["id"], make_customer_headers(cid))
    api.pay_order(order["id"], pay_order_payload("SUCCEEDED"), make_customer_headers(cid))
    shipped = validate_success(api.ship_order(order["id"], INV), 200)

    assert shipped["accrued_points"] == 10, "round(350*0.015)=5 per line, 5+5=10 (not round(700*0.015)=11)"
    cust_after = validate_success(api.get_customer(cid, make_customer_headers(cid)), 200)
    assert cust_after["loyalty_points_balance"] == 10


def test_loyalty_accrual_credited_on_ship(api):
    """PRD §3.7: "Loyalty points are accrued — recorded on the order's accrued_points and
    credited to the customer only when the order ships."

    Design: Difficulty/combinatorial_formula/combinatorial_loyalty_accrual_rounding_order
    """
    sku, _ = create_active_sku_with_lot(name="Mini Sauce 2", category="HOT_SAUCE",
                                        storage_class="AMBIENT", unit_price_cents=350,
                                        produced_units=10)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    shipped = build_shipped_order(cid, [(sku["id"], 1), (sku["id"], 1)])
    cust_after = validate_success(api.get_customer(cid, make_customer_headers(cid)), 200)
    assert cust_after["loyalty_points_balance"] == shipped["accrued_points"] == 10


# ───────────────────────── renewal charge: provisional vs final ─────────────────────────

def test_renewal_provisional_vs_final_charge_diverge(api):
    """PRD §3.9: "a CLASSIC subscriber in Z2 with no staged swap has a provisional estimate
    of 5700 cents (4900 plus 800) but a final charge of 5455 cents — 4900 times 0.95 rounded
    half up, which is 4655, plus the 800 zone base."

    Design: Difficulty/dual_variant_calc/dual_variant_renewal_charge_provisional_vs_final
    """
    customer, sku, sub = setup_subscription_due_for_renewal(
        tier="CLASSIC", cadence_days=28, home_zone="Z2", unit_price_cents=4900,
        due_iso="2026-04-01T00:00:00Z")

    assert sub["provisional_charge_cents"] == 5700, "PROVISIONAL: 4900 CLASSIC + 800 Z2, no loyalty discount"

    validate_success(api.renew_subscription(sub["id"], ADMIN), 200)
    data, _meta = validate_paginated(api.list_orders(ADMIN, params={"subscription_id": sub["id"]}))
    assert len(data) >= 1, "renewal created a SUBSCRIPTION order"
    renewal_order = data[0]
    assert renewal_order["total_cents"] == 5455, "FINAL: round_half_up(4900*0.95)=4655 + 800 Z2"
    assert renewal_order["total_cents"] != sub["provisional_charge_cents"]


def test_renewal_provisional_estimate_on_creation(api):
    """PRD §3.9: "So the provisional estimate is the current tier's monthly price plus the
    home-zone base."
    PRD §3.9: "The tier monthly prices are 2900 cents for STARTER, 4900 for CLASSIC, and
    8900 for RESERVE; the zone bases are the same as for orders — 500, 800, 1200, and 1800
    cents for Z1 through Z4."

    Design: Difficulty/dual_variant_calc/dual_variant_renewal_charge_provisional_vs_final
    """
    sku, _ = create_active_sku_with_lot(name="Prov Coffee", category="COFFEE",
                                        storage_class="AMBIENT", unit_price_cents=4900)
    cust = create_customer(home_zone="Z2")
    cid = cust["id"]
    sub = get_success_data(api.create_subscription(
        {"customer_id": cid, "sku_id": sku["id"], "tier": "CLASSIC", "cadence_days": 28},
        make_customer_headers(cid)))
    assert sub["provisional_charge_cents"] == 5700, "4900 CLASSIC + 800 Z2"


# ───────────────────────── bulk quote tiers ─────────────────────────

def test_bulk_quote_top_tier_total(api):
    """PRD §3.11: "a line subtotal of at least 100000 cents yields 20 percent discount and
    3 percent handling"
    PRD §3.11: "The handling_cents is the handling percentage applied to that discounted
    subtotal, rounded half up. Branded gift wrap adds 350 cents per gift_box_count. The
    quote's total_cents is the discounted subtotal plus handling_cents plus that gift-wrap amount."

    Design: Corner/calculations/corporate_bulk_quote_top_tier_total
    """
    buyer, sku, bq = setup_draft_bulk_quote(quantity=200, unit_price_cents=1500, gift_box_count=10)
    quoted = validate_success(api.quote_bulk_quote(bq["id"], ADMIN), 200)
    assert quoted["discount_cents"] == 60000, "300000 * 0.20"
    assert quoted["handling_cents"] == 7200, "(300000-60000) * 0.03"
    assert quoted["total_cents"] == 250700, "240000 + 7200 + 3500 gift wrap"


def test_bulk_quote_below_20000_no_discount(api):
    """PRD §3.11: "and below 20000 yields no discount and 6 percent handling."

    Design: Corner/calculations/bulk_quote_tier_boundary_below_20000_no_discount
    """
    buyer, sku, bq = setup_draft_bulk_quote(quantity=10, unit_price_cents=1000)
    quoted = validate_success(api.quote_bulk_quote(bq["id"], ADMIN), 200)
    assert quoted["discount_cents"] == 0
    assert quoted["handling_cents"] == 600, "10000 * 0.06"
    assert quoted["total_cents"] == 10600
