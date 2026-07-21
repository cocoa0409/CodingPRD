"""Order pricing (discount tiers, loyalty redemption, shipping threshold) and
per-line loyalty earning."""
from test_helpers import (
    validate_success, validate_paginated, TEST_USERS,
    make_customer, make_product, make_variant, make_order, add_line,
    place_order, fulfill_order, setup_fulfilled_order,
)
from test_helpers.test_users import make_customer_headers

FULFILL = TEST_USERS["fulfillment_headers"]


def _lines_by_id(api, order_id, cust_id):
    data, _ = validate_paginated(api.list_order_lines(order_id, make_customer_headers(cust_id)))
    return {ln["id"]: ln for ln in data}


# ─── Difficulty/combinatorial_formula/order_pricing_shipping_threshold_after_loyalty_mode_c ───
def _order_below_ship_threshold_after_loyalty(api):
    """Earn 600 points on a fulfilled 60000 order, then place a fresh 8000 order
    redeeming 600 so net-after-loyalty (7400) drops below the free-ship threshold."""
    ctx = setup_fulfilled_order(60000, on_hand_qty=2, concentration="PARFUM")
    cust_id = ctx["cust_id"]
    prod = make_product(name="Std", brand="House", concentration="EDT")
    var = make_variant(prod["id"], kind="FULL_BOTTLE", volume_ml=50,
                       unit_price_cents=8000, on_hand_qty=2)
    order = make_order(cust_id)
    add_line(order["id"], cust_id, var["id"], 1)
    resp = api.place_order(order["id"], {"redeem_points": 600}, make_customer_headers(cust_id))
    return validate_success(resp, 200)


def test_shipping_charged_when_loyalty_drops_net_below_threshold(api):
    """PRD §3.2: "Shipping is evaluated on this net-after-loyalty figure, before
    shipping itself is added: `shipping_fee_cents` is zero when net-after-loyalty
    is at least seventy-five dollars (7500 cents) and otherwise a flat five
    dollars and ninety-five cents (595 cents)."

    Design: Difficulty/combinatorial_formula/order_pricing_shipping_threshold_after_loyalty_mode_c
    """
    order = _order_below_ship_threshold_after_loyalty(api)
    assert order["subtotal_cents"] == 8000
    assert order["loyalty_redeemed_cents"] == 600
    assert order["shipping_fee_cents"] == 595


def test_total_is_net_after_loyalty_plus_shipping(api):
    """PRD §3.2: "Finally, `total_cents` — the amount charged — is the
    net-after-loyalty amount plus the shipping fee."

    Design: Difficulty/combinatorial_formula/order_pricing_shipping_threshold_after_loyalty_mode_c
    """
    order = _order_below_ship_threshold_after_loyalty(api)
    # net_after_loyalty = 8000 - 600 = 7400; + 595 shipping = 7995
    assert order["total_cents"] == 7995


def test_order_pricing_5pct_tier_discount(api):
    """PRD §3.2: "a subtotal from one hundred dollars up to but not including
    three hundred dollars (at least 10000 cents and below 30000 cents) earns five
    percent. The `discount_cents` is the subtotal multiplied by that rate, rounded
    half up to whole cents."

    Design: Corner/calculations/order_pricing_5pct_tier_correct_result
    """
    cust = make_customer()
    cust_id = cust["id"]
    prod = make_product(concentration="EDP")
    v_big = make_variant(prod["id"], kind="FULL_BOTTLE", unit_price_cents=12000, on_hand_qty=5)
    v_small = make_variant(prod["id"], kind="DECANT", volume_ml=10, unit_price_cents=3500, on_hand_qty=5)
    order = make_order(cust_id)
    add_line(order["id"], cust_id, v_big["id"], 1)
    add_line(order["id"], cust_id, v_small["id"], 2)
    resp = api.place_order(order["id"], {"redeem_points": 0}, make_customer_headers(cust_id))
    data = validate_success(resp, 200)
    assert data["subtotal_cents"] == 19000
    assert data["discount_cents"] == 950
    assert data["shipping_fee_cents"] == 0
    assert data["total_cents"] == 18050


# ─── Difficulty/combinatorial_formula/loyalty_round_per_line_then_sum_mode_b ───
def _fulfilled_two_sample_lines(api):
    """One BRONZE customer, two SAMPLE variants at 250 each, one line of each,
    order placed and fulfilled. Returns (cust_id, order_id, line1_id, line2_id)."""
    cust_id = make_customer()["id"]
    prod = make_product(name="Samples", brand="House", concentration="EDT")
    s1 = make_variant(prod["id"], kind="SAMPLE", volume_ml=2, unit_price_cents=250, on_hand_qty=20)
    s2 = make_variant(prod["id"], kind="SAMPLE", volume_ml=2, unit_price_cents=250, on_hand_qty=20)
    order = make_order(cust_id)
    l1 = add_line(order["id"], cust_id, s1["id"], 1)
    l2 = add_line(order["id"], cust_id, s2["id"], 1)
    place_order(order["id"], cust_id, 0)
    fulfill_order(order["id"])
    return cust_id, order["id"], l1["id"], l2["id"]


def test_per_line_loyalty_points_rounded_before_summing(api):
    """PRD §3.3: "for each active line, the server takes the line's total in
    cents, divides by one hundred to convert to dollars, multiplies by the tier
    multiplier, and rounds half up to a whole number of points; that per-line
    result is stored on the line's `points_earned`."

    Design: Difficulty/combinatorial_formula/loyalty_round_per_line_then_sum_mode_b
    """
    cust_id, order_id, l1, l2 = _fulfilled_two_sample_lines(api)
    lines = _lines_by_id(api, order_id, cust_id)
    assert lines[l1]["points_earned"] == 3, "round_half_up(250/100)=3"
    assert lines[l2]["points_earned"] == 3


def test_balance_is_sum_of_rounded_per_line_points(api):
    """PRD §3.3: "The order's earned points are the sum of these already-rounded
    per-line values (rounding each line before summing, not rounding once after
    summing, so that per-line remainders are preserved)."

    Design: Difficulty/combinatorial_formula/loyalty_round_per_line_then_sum_mode_b
    """
    cust_id, order_id, l1, l2 = _fulfilled_two_sample_lines(api)
    cust = validate_success(api.get_customer(cust_id, make_customer_headers(cust_id)), 200)
    assert cust["loyalty_points_balance"] == 6, "3 + 3, not round(500/100)=5"
