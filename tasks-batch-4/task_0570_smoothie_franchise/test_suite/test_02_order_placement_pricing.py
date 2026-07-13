"""Order placement pricing, nutrition, and allergen-safety corners."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_open_store, create_ingredient, create_inventory_lot, create_menu_item,
    create_boost, create_customer, create_subscription, renew_subscription,
    place_order, order_line, make_customer_headers,
    create_order_payload,
)


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/order_line_tiered_pricing_with_credit
# ---------------------------------------------------------------------------

def _silver_credit_order(api):
    fr, st = create_open_store(api)
    ing = create_ingredient(api, name="Spinach")
    create_inventory_lot(api, st["id"], ing["id"], qty_received=100, unit_cost_cents=2)
    mi = create_menu_item(api, name="Big Green", category="SMOOTHIE", base_price_cents=600,
                          recipe=[{"ingredient_id": ing["id"], "base_qty": 40}], base_calories=200)
    boost = create_boost(api, name="Protein", price_cents=150, calories=100)
    cust = create_customer(api, email="c3@x.com", full_name="C Three")
    sub = create_subscription(api, cust["id"], tier="PREMIUM", monthly_fee_cents=1999,
                              included_smoothie_credits=4, renewal_bonus_points=500)
    renew_subscription(api, sub["id"], "SUCCESS")  # lifetime 500 -> SILVER, credits reset to 4
    order = place_order(api, st["id"], cust["id"],
                        [order_line(mi["id"], "MEDIUM", [boost["id"]])],
                        use_subscription_credit=True)
    return order


def test_tiered_pricing_with_credit_subtotal_and_credits(api):
    """PRD §3.5: "When a credit applies, the covered amount is the size base (the credit
    waives the SMOOTHIE base price only; boosts are still charged); otherwise the covered
    amount is 0."
    PRD §3.5: "The `tier_discount_cents` for the line is the subsidized base multiplied by
    the customer's loyalty discount rate — 0% for `BRONZE`, 5% for `SILVER`, 10% for `GOLD`
    — rounded half up to whole cents."
    PRD §3.5: "The number of credits actually applied across the order is recorded as
    `credits_used`."

    Design: Difficulty/combinatorial_formula/order_line_tiered_pricing_with_credit
    """
    order = _silver_credit_order(api)
    # size_base 700, boost 150, gross 850; credit waives 700 -> subsidized 150;
    # SILVER 5% of 150 = round(7.5) = 8; line_net = 142.
    assert order["subtotal_cents"] == 142, f"Expected subtotal 142, got {order['subtotal_cents']}"
    assert order["gross_merch_cents"] == 850, (
        f"Expected gross_merch 850, got {order['gross_merch_cents']}"
    )
    assert order["credits_used"] == 1, f"Expected credits_used 1, got {order['credits_used']}"


def test_tiered_pricing_with_credit_total(api):
    """PRD §3.5: "The `tax_cents` is `discounted_subtotal_cents` multiplied by an 8% tax
    rate, rounded half up in a single order-level rounding step."
    PRD §3.5: "The `total_cents` is `discounted_subtotal_cents` plus `tax_cents`."

    Design: Difficulty/combinatorial_formula/order_line_tiered_pricing_with_credit
    """
    order = _silver_credit_order(api)
    # discounted_subtotal 142, tax round(142*0.08)=round(11.36)=11, total 153.
    assert order["total_cents"] == 153, f"Expected total 153, got {order['total_cents']}"


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/order_total_rounding_per_line_then_sum
# ---------------------------------------------------------------------------

def _silver_two_line_order(api):
    fr, st = create_open_store(api)
    ing = create_ingredient(api, name="Spinach")
    create_inventory_lot(api, st["id"], ing["id"], qty_received=400, unit_cost_cents=2)
    mi = create_menu_item(api, name="Green Machine", category="SMOOTHIE", base_price_cents=500,
                          recipe=[{"ingredient_id": ing["id"], "base_qty": 50}], base_calories=200)
    boost = create_boost(api, name="Protein", price_cents=150, calories=100)
    cust = create_customer(api, email="c4@x.com", full_name="C Four")
    sub = create_subscription(api, cust["id"], tier="BASIC", monthly_fee_cents=999,
                              included_smoothie_credits=0, renewal_bonus_points=500)
    renew_subscription(api, sub["id"], "SUCCESS")  # lifetime 500 -> SILVER
    line = order_line(mi["id"], "MEDIUM", [boost["id"]])
    order = place_order(api, st["id"], cust["id"], [dict(line), dict(line)])
    return order


def test_order_total_rounds_per_line_then_sums(api):
    """PRD §3.5: "Rounding happens per line first, then the order aggregates."
    PRD §3.5: "The `subtotal_cents` is the sum of every `line_net_cents`."

    Design: Difficulty/combinatorial_formula/order_total_rounding_per_line_then_sum
    """
    order = _silver_two_line_order(api)
    # each line gross 750, SILVER 5% of 750 = round(37.5) = 38, line_net 712;
    # two lines -> 1424 (a sum-then-round reading would give 1425).
    assert order["subtotal_cents"] == 1424, (
        f"Expected per-line-rounded subtotal 1424, got {order['subtotal_cents']}"
    )


def test_order_total_rounding_order_level_tax(api):
    """PRD §3.5: "The `tax_cents` is `discounted_subtotal_cents` multiplied by an 8% tax
    rate, rounded half up in a single order-level rounding step."
    PRD §3.5: "The `total_cents` is `discounted_subtotal_cents` plus `tax_cents`."

    Design: Difficulty/combinatorial_formula/order_total_rounding_per_line_then_sum
    """
    order = _silver_two_line_order(api)
    # discounted_subtotal 1424, tax round(1424*0.08)=round(113.92)=114, total 1538.
    assert order["total_cents"] == 1538, f"Expected total 1538, got {order['total_cents']}"


# ---------------------------------------------------------------------------
# Corner/consistency_model/order_pricing_visible_in_create_response
# ---------------------------------------------------------------------------

def test_order_pricing_visible_in_create_response(api):
    """PRD §3.5: "The `subtotal_cents` is the sum of every `line_net_cents`."
    PRD §3.5: "The `tax_cents` is `discounted_subtotal_cents` multiplied by an 8% tax
    rate, rounded half up in a single order-level rounding step."
    PRD §3.5: "The `total_cents` is `discounted_subtotal_cents` plus `tax_cents`."

    Design: Corner/consistency_model/order_pricing_visible_in_create_response
    """
    fr, st = create_open_store(api)
    ing = create_ingredient(api, name="Spinach")
    create_inventory_lot(api, st["id"], ing["id"], qty_received=100, unit_cost_cents=2)
    mi = create_menu_item(api, name="Green Machine", category="SMOOTHIE", base_price_cents=500,
                          recipe=[{"ingredient_id": ing["id"], "base_qty": 50}], base_calories=200)
    boost = create_boost(api, name="Protein", price_cents=150, calories=100)
    cust = create_customer(api, email="im@x.com", full_name="Immed")
    resp = api.create_order(
        create_order_payload(st["id"], [order_line(mi["id"], "MEDIUM", [boost["id"]])]),
        make_customer_headers(cust["id"]),
    )
    data = validate_success(resp, expected_status=201)
    # BRONZE (no discount): line gross 600+150=750, subtotal 750, tax round(60.0)=60, total 810.
    assert data["subtotal_cents"] == 750, f"Expected subtotal 750, got {data['subtotal_cents']}"
    assert data["tax_cents"] == 60, f"Expected tax 60, got {data['tax_cents']}"
    assert data["total_cents"] == 810, f"Expected total 810, got {data['total_cents']}"


# ---------------------------------------------------------------------------
# Corner/entities/order_nutrition_computed_from_size_and_boosts
# ---------------------------------------------------------------------------

def test_order_nutrition_computed_from_size_and_boosts(api):
    """PRD §3.5: "Each line's `line_calories` is the menu item's `base_calories` scaled
    by a size quantity factor — 1.0 for `SMALL`, 1.5 for `MEDIUM`, 2.0 for `LARGE` —
    rounded half up to whole calories, then increased by the sum of each boost's
    `calories`."

    Design: Corner/entities/order_nutrition_computed_from_size_and_boosts
    """
    fr, st = create_open_store(api)
    ing = create_ingredient(api, name="Spinach")
    create_inventory_lot(api, st["id"], ing["id"], qty_received=100, unit_cost_cents=2)
    mi = create_menu_item(api, name="Green Machine", category="SMOOTHIE", base_price_cents=500,
                          recipe=[{"ingredient_id": ing["id"], "base_qty": 50}], base_calories=200)
    boost = create_boost(api, name="Protein", price_cents=150, calories=100)
    cust = create_customer(api, email="n@x.com", full_name="Nut")
    order = place_order(api, st["id"], cust["id"], [order_line(mi["id"], "MEDIUM", [boost["id"]])])
    # round(200*1.5)=300 + boost 100 = 400.
    assert order["total_calories"] == 400, (
        f"Expected total_calories 400, got {order['total_calories']}"
    )


# ---------------------------------------------------------------------------
# Difficulty/priority_pair_validation_conflict/allergen_safety_beats_inventory_constraint
# The PRD's fixed priority order (§2.9) does not pin allergen (a business-safety
# rule) ahead of the inventory business rule, so each is exercised in isolation
# with sufficient stock present — leaving the allergen check as the sole failure.
# ---------------------------------------------------------------------------

def test_menu_item_allergen_conflict_rejected(api):
    """PRD §3.5: "If any line's allergen set intersects the customer's `allergen_avoid`,
    the order is rejected with `ERR_ALLERGEN_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/allergen_safety_beats_inventory_constraint
    """
    fr, st = create_open_store(api)
    ing = create_ingredient(api, name="Milk", unit="ML", standard_cost_cents_per_unit=1)
    create_inventory_lot(api, st["id"], ing["id"], qty_received=200, unit_cost_cents=1)
    mi = create_menu_item(api, name="Milkshake", category="SMOOTHIE", base_price_cents=500,
                          recipe=[{"ingredient_id": ing["id"], "base_qty": 100}],
                          base_calories=300, allergen_tags=["milk"])
    cust = create_customer(api, email="c8@x.com", full_name="C Eight", allergen_avoid=["milk"])
    resp = api.create_order(
        create_order_payload(st["id"], [order_line(mi["id"], "SMALL")]),
        make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ALLERGEN_CONFLICT.value)


def test_boost_allergen_conflict_rejected(api):
    """PRD §3.5: "Each line's `line_allergens` is the union of the menu item's
    `allergen_tags` with the `allergen_tags` of its boosts, and the order's
    `allergen_summary` is the union of all lines' `line_allergens`."
    PRD §3.5: "If any line's allergen set intersects the customer's `allergen_avoid`,
    the order is rejected with `ERR_ALLERGEN_CONFLICT`."

    Design: Difficulty/priority_pair_validation_conflict/allergen_safety_beats_inventory_constraint
    """
    fr, st = create_open_store(api)
    ing = create_ingredient(api, name="Spinach")
    create_inventory_lot(api, st["id"], ing["id"], qty_received=200, unit_cost_cents=2)
    mi = create_menu_item(api, name="Green Machine", category="SMOOTHIE", base_price_cents=500,
                          recipe=[{"ingredient_id": ing["id"], "base_qty": 50}], base_calories=200)
    boost = create_boost(api, name="Peanut Butter", price_cents=150, calories=100,
                         allergen_tags=["peanut"])
    cust = create_customer(api, email="c8b@x.com", full_name="C Eight B", allergen_avoid=["peanut"])
    resp = api.create_order(
        create_order_payload(st["id"], [order_line(mi["id"], "SMALL", [boost["id"]])]),
        make_customer_headers(cust["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ALLERGEN_CONFLICT.value)
