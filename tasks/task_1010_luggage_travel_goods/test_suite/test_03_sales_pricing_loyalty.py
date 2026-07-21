"""Sales-order pricing, gift wrap, and the loyalty ledger (provisional/final points, spend, refund)."""
import test_helpers as H


# ==========================================================================
# Queue A — combinatorial formula: per-line-round-then-sum
# ==========================================================================
def test_sales_pricing_rounds_each_line_before_summing(api):
    """PRD §2.6: "each line is rounded to whole cents first, and only the rounded line amounts are
    added together."

    Design: Difficulty/combinatorial_formula/sales_pricing_per_line_round_then_sum_mode_b
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=100)
    order = H.new_sales_order(customer["id"], api)
    H.new_sales_order_line(order["id"], product["id"], api, unit_price_cents=100, qty=1, line_discount_pct=0.005)
    H.new_sales_order_line(order["id"], product["id"], api, unit_price_cents=100, qty=1, line_discount_pct=0.005)
    after = H.get_sales_order(order["id"], api)
    assert after["subtotal_cents"] == 200


def test_sales_pricing_taxes_the_taxable_base(api):
    """PRD §3.5: "The taxable base is the subtotal minus the loyalty discount, and `tax_cents` is
    that taxable base multiplied by the tax rate of 0.08, rounded half-up."

    Design: Difficulty/combinatorial_formula/sales_pricing_per_line_round_then_sum_mode_b
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=100)
    order = H.new_sales_order(customer["id"], api)
    H.new_sales_order_line(order["id"], product["id"], api, unit_price_cents=100, qty=1, line_discount_pct=0.005)
    H.new_sales_order_line(order["id"], product["id"], api, unit_price_cents=100, qty=1, line_discount_pct=0.005)
    after = H.get_sales_order(order["id"], api)
    assert after["total_cents"] == 216


# ==========================================================================
# Queue B — calculations: gift wrap fee
# ==========================================================================
def test_gift_order_applies_wrap_fee(api):
    """PRD §3.5: "The `gift_wrap_fee_cents` is 800 cents when the order is a gift and zero
    otherwise. The `total_cents` is the taxable base plus the tax plus the gift-wrap fee."

    Design: Corner/calculations/sales_order_gift_wrap_fee_applied
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=10000)
    order, _ = H.sales_order_with_line(
        customer["id"], product["id"],
        line_overrides={"unit_price_cents": 10000, "qty": 1},
        order_overrides={"is_gift": True, "gift_message": "Happy trip"}, api=api)
    after = H.get_sales_order(order["id"], api)
    assert after["gift_wrap_fee_cents"] == 800
    assert after["total_cents"] == 11600


# ==========================================================================
# Queue A — dual-variant calc: provisional vs final points across a tier change
# ==========================================================================
def test_provisional_points_use_tier_at_creation(api):
    """PRD §3.2: "At order creation this is computed using the customer's tier **at creation time**
    and stored as `provisional_points`, a non-binding estimate that is not added to the balance."

    Design: Difficulty/dual_variant_calc/loyalty_points_provisional_vs_final_tier_change
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=20000)
    H.captured_order_with_line(customer["id"], product["id"], unit_price_cents=50000, qty=1, api=api)  # -> SILVER
    order_x, _ = H.sales_order_with_line(
        customer["id"], product["id"], line_overrides={"unit_price_cents": 20000, "qty": 1}, api=api)
    assert order_x["provisional_points"] == 237


def test_final_points_use_tier_at_capture_after_upgrade(api):
    """PRD §3.2: "At payment capture it is recomputed using the customer's tier **at capture time**,
    which may be higher if intervening activity upgraded the customer; that final figure is stored
    as `points_credited` and added to `points_balance`."

    Design: Difficulty/dual_variant_calc/loyalty_points_provisional_vs_final_tier_change
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=20000)
    H.captured_order_with_line(customer["id"], product["id"], unit_price_cents=50000, qty=1, api=api)  # -> SILVER
    order_x, _ = H.sales_order_with_line(
        customer["id"], product["id"], line_overrides={"unit_price_cents": 20000, "qty": 1}, api=api)
    H.captured_order_with_line(customer["id"], product["id"], unit_price_cents=110000, qty=1, api=api)  # -> GOLD
    H.get_success_data(api.capture_sales_order(order_x["id"], H.TEST_USERS["associate_headers"]))
    after = H.get_sales_order(order_x["id"], api)
    cust_after = H.get_customer(customer["id"], api)
    assert after["points_credited"] == 285
    assert cust_after["tier"] == "GOLD"


# ==========================================================================
# Queue A — transitive cascade: capture spend crosses a tier threshold
# ==========================================================================
def test_capture_raises_lifetime_spend_and_upgrades_tier(api):
    """PRD §3.5: "the net merchandise (subtotal minus loyalty discount) is added to the customer's
    `lifetime_spend_cents`, which may cross a tier threshold and upgrade the customer."
    PRD §3.2: "a customer's `tier` is the highest tier whose threshold is less than or equal to
    their `lifetime_spend_cents` (so exactly 50000 lifetime is `SILVER`, exactly 150000 is `GOLD`,
    exactly 500000 is `PLATINUM`)."

    Design: Difficulty/transitive_cascade/capture_lifetime_spend_triggers_tier_upgrade_depth2
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=50000)
    H.captured_order_with_line(customer["id"], product["id"], unit_price_cents=50000, qty=1, api=api)
    cust_after = H.get_customer(customer["id"], api)
    assert cust_after["lifetime_spend_cents"] == 50000
    assert cust_after["tier"] == "SILVER"


def test_capture_credits_points_at_base_rate(api):
    """PRD §3.2: "That whole number is then multiplied by the tier multiplier — `BRONZE` earns 1.00
    times, `SILVER` 1.25 times, `GOLD` 1.50 times, and `PLATINUM` 2.00 times — and the product is
    floored again to a whole number of points."

    Design: Difficulty/transitive_cascade/capture_lifetime_spend_triggers_tier_upgrade_depth2
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=50000)
    H.captured_order_with_line(customer["id"], product["id"], unit_price_cents=50000, qty=1, api=api)
    cust_after = H.get_customer(customer["id"], api)
    assert cust_after["points_balance"] == 500


# ==========================================================================
# Queue A — compensating invariant: capture then refund conserves points
# ==========================================================================
def test_refund_reverses_credited_points_to_zero(api, manager_headers):
    """PRD §3.5: "the refund subtracts the previously credited `points_credited` from
    `points_balance` and subtracts the same net merchandise from `lifetime_spend_cents`, conserving
    both invariants."

    Design: Difficulty/compensating_invariant/points_capture_then_refund_conserves_balance
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=50000)
    order = H.captured_order_with_line(customer["id"], product["id"], unit_price_cents=50000, qty=1, api=api)
    assert order["points_credited"] == 500
    H.get_success_data(api.refund_sales_order(order["id"], manager_headers))
    cust_after = H.get_customer(customer["id"], api)
    assert cust_after["points_balance"] == 0


def test_refund_reverses_lifetime_spend_to_zero(api, manager_headers):
    """PRD §3.5: "the refund subtracts the previously credited `points_credited` from
    `points_balance` and subtracts the same net merchandise from `lifetime_spend_cents`, conserving
    both invariants."

    Design: Difficulty/compensating_invariant/points_capture_then_refund_conserves_balance
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=50000)
    order = H.captured_order_with_line(customer["id"], product["id"], unit_price_cents=50000, qty=1, api=api)
    H.get_success_data(api.refund_sales_order(order["id"], manager_headers))
    cust_after = H.get_customer(customer["id"], api)
    assert cust_after["lifetime_spend_cents"] == 0


# ==========================================================================
# Queue B — consistency: credited points visible immediately after capture
# ==========================================================================
def test_captured_points_visible_on_customer_read(api):
    """PRD §3.2: "The `points_balance` is credited when a sale is captured and debited when it is
    refunded, and it must always equal the sum of points earned on captured orders minus the sum
    reversed on refunded orders."

    Design: Corner/consistency_model/capture_credits_points_visible_in_same_flow
    """
    customer = H.new_customer(api)
    product = H.new_product(api, msrp_cents=10000)
    H.captured_order_with_line(customer["id"], product["id"], unit_price_cents=10000, qty=1, api=api)
    cust_after = H.get_customer(customer["id"], api)
    assert cust_after["points_balance"] == 100
