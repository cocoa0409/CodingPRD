"""Pricing engine: tiered + subscriber-perk discount, the free-ship threshold,
loyalty-tier thresholds, and the settled-vs-pending distinction.
"""
from test_helpers import (
    validate_success,
    make_shopper_headers,
    new_customer,
    new_product,
    new_variant,
    loyalty_adjust,
    new_subscription,
    place_order,
    pay_order,
    setup_buyable,
)


# ---- combinatorial_formula: order_discount_tiered_nonlinear_mode_a ----

def test_gold_plus_active_subscription_discount_and_free_ship(api):
    """PRD §3.4: "a `GOLD` customer earns 10 percent (0.10)."
    PRD §3.4: "a customer who currently holds a subscription in the `ACTIVE`
    state earns an additional subscriber perk of 5 percent (0.05)."
    PRD §3.4: "The `discount_cents` is the subtotal times that effective rate,
    rounded half up."
    PRD §3.4: "if it is at least the free-shipping threshold of 8000 cents,
    shipping is 0."

    Design: Difficulty/combinatorial_formula/order_discount_tiered_nonlinear_mode_a
    """
    cust = new_customer(api)
    loyalty_adjust(api, cust["id"], 5000)  # -> GOLD
    new_subscription(api, cust["id"], plan_tier="CAPSULE_PLUS", monthly_fee_cents=4000)
    product = new_product(api, category="MATERNITY", buy_price_cents=10000)
    variant = new_variant(api, product["id"], inventory_on_hand=5)
    order = place_order(api, cust["id"], variant["id"], "BUY", quantity=1)
    assert order["subtotal_cents"] == 10000
    assert order["discount_cents"] == 1500  # min(0.20, 0.10+0.05) * 10000
    assert order["shipping_cents"] == 0     # net 8500 >= 8000
    assert order["grand_total_cents"] == 8500


def test_silver_plus_active_subscription_additive_rate(api):
    """PRD §3.4: "a `SILVER` customer earns 5 percent (0.05)."
    PRD §3.4: "The base rate and the perk rate are summed, and the effective
    rate is then capped so it never exceeds 20 percent (0.20)."
    PRD §3.4: "The `discount_cents` is the subtotal times that effective rate,
    rounded half up."

    Design: Difficulty/combinatorial_formula/order_discount_tiered_nonlinear_mode_a
    """
    cust = new_customer(api)
    loyalty_adjust(api, cust["id"], 2000)  # -> SILVER
    new_subscription(api, cust["id"], plan_tier="CAPSULE_BASIC", monthly_fee_cents=3000)
    product = new_product(api, category="MATERNITY", buy_price_cents=10000)
    variant = new_variant(api, product["id"], inventory_on_hand=5)
    order = place_order(api, cust["id"], variant["id"], "BUY", quantity=1)
    assert order["subtotal_cents"] == 10000
    assert order["discount_cents"] == 1000  # (0.05 + 0.05) * 10000


# ---- dual_variant_calc: loyalty_settled_vs_provisional_tier ----

def test_settled_tier_ignores_pending_earned_points(api):
    """PRD §3.4: "the customer's settled `loyalty_tier` ... counts only points
    already earned from completed orders plus manual adjustments."
    PRD §3.4: "These points are computed now but are not credited to any balance
    until the order is fulfilled."
    PRD §3.4: "one with at least 2000 (but under 5000) is `SILVER`."

    Design: Difficulty/dual_variant_calc/loyalty_settled_vs_provisional_tier
    """
    cust = new_customer(api)
    loyalty_adjust(api, cust["id"], 4900)  # SILVER
    product = new_product(api, category="NURSING", buy_price_cents=20000)
    variant = new_variant(api, product["id"], inventory_on_hand=10)
    order = place_order(api, cust["id"], variant["id"], "BUY", quantity=1)
    pay_order(api, order["id"], cust["id"], redeemed_points=0)  # PAID but not fulfilled

    order_read = validate_success(api.get_order(order["id"], make_shopper_headers(cust["id"])), 200)
    cust_read = validate_success(api.get_customer(cust["id"], make_shopper_headers(cust["id"])), 200)
    # SILVER discount 5% on 20000 = 1000; earned = floor((20000-1000)/100) = 190.
    assert order_read["earned_points"] == 190
    assert cust_read["lifetime_points"] == 4900   # pending points NOT yet counted
    assert cust_read["loyalty_tier"] == "SILVER"  # settled tier unmoved by the in-flight order


def test_settled_tier_bronze_below_threshold_despite_pending(api):
    """PRD §3.4: "anyone below 2000 is `BRONZE`."
    PRD §3.4: "which counts only points already earned from completed orders plus
    manual adjustments."
    PRD §3.4: "These points are computed now but are not credited to any balance
    until the order is fulfilled."

    Design: Difficulty/dual_variant_calc/loyalty_settled_vs_provisional_tier
    """
    cust = new_customer(api)
    loyalty_adjust(api, cust["id"], 1900)  # BRONZE (below 2000)
    product = new_product(api, category="NURSING", buy_price_cents=20000)
    variant = new_variant(api, product["id"], inventory_on_hand=10)
    order = place_order(api, cust["id"], variant["id"], "BUY", quantity=1)
    pay_order(api, order["id"], cust["id"], redeemed_points=0)

    cust_read = validate_success(api.get_customer(cust["id"], make_shopper_headers(cust["id"])), 200)
    assert cust_read["lifetime_points"] == 1900   # pending earned points not credited
    assert cust_read["loyalty_tier"] == "BRONZE"


# ---- boundary_precision_check: loyalty_tier_gold_boundary_5000 ----

def test_loyalty_tier_gold_boundary_4999_5000(api, platform_admin_headers):
    """PRD §3.4: "a customer with at least 5000 lifetime points is `GOLD`, one
    with at least 2000 (but under 5000) is `SILVER`, and anyone below 2000 is
    `BRONZE`. Both thresholds are inclusive."

    Design: Difficulty/boundary_precision_check/loyalty_tier_gold_boundary_5000
    """
    cust = new_customer(api)
    loyalty_adjust(api, cust["id"], 4999)
    at_4999 = validate_success(api.get_customer(cust["id"], platform_admin_headers), 200)
    assert at_4999["loyalty_tier"] == "SILVER"
    loyalty_adjust(api, cust["id"], 1)  # -> 5000
    at_5000 = validate_success(api.get_customer(cust["id"], platform_admin_headers), 200)
    assert at_5000["loyalty_tier"] == "GOLD"


def test_loyalty_tier_silver_boundary_1999_2000(api, platform_admin_headers):
    """PRD §3.4: "one with at least 2000 (but under 5000) is `SILVER`, and anyone
    below 2000 is `BRONZE`. Both thresholds are inclusive."

    Design: Difficulty/boundary_precision_check/loyalty_tier_gold_boundary_5000
    """
    cust = new_customer(api)
    loyalty_adjust(api, cust["id"], 1999)
    at_1999 = validate_success(api.get_customer(cust["id"], platform_admin_headers), 200)
    assert at_1999["loyalty_tier"] == "BRONZE"
    loyalty_adjust(api, cust["id"], 1)  # -> 2000
    at_2000 = validate_success(api.get_customer(cust["id"], platform_admin_headers), 200)
    assert at_2000["loyalty_tier"] == "SILVER"


# ---- Corner: free_ship_threshold_inclusive_at_8000 ----

def test_free_ship_threshold_inclusive_at_8000(api):
    """PRD §3.4: "if it is at least the free-shipping threshold of 8000 cents,
    shipping is 0; otherwise a flat 799 cents is charged."
    PRD §3.4: "the `grand_total_cents` charged is the net after discount, minus
    the redeemed cents, plus the shipping, and then floored at zero."

    Design: Corner/calculations/free_ship_threshold_inclusive_at_8000
    """
    base = setup_buyable(api, buy_price_cents=8000, inventory_on_hand=5, category="MATERNITY")
    order = place_order(api, base["customer"]["id"], base["variant"]["id"], "BUY", quantity=1)
    assert order["shipping_cents"] == 0
    assert order["grand_total_cents"] == 8000
