"""Order pricing (provisional vs final, bulk+loyalty cap) and loyalty points accounting."""
import test_helpers as H


def _two_line_order(price1, price2, qty1, qty2, grant_points=0, order_type="RETAIL", checkout=True):
    """RETAIL order with two RESERVED lines on two distinct soap skus/batches.

    Returns {customer, order, s1, s2, b1, b2, l1, l2}.
    """
    product = H.new_product(product_type="SOAP")
    s1 = H.new_sku(product["id"], list_price_cents=price1, scent="Lemon")
    s2 = H.new_sku(product["id"], list_price_cents=price2, scent="Lime")
    b1 = H.release_batch(H.new_batch(s1["id"], quantity_produced=100)["id"])
    b2 = H.release_batch(H.new_batch(s2["id"], quantity_produced=100)["id"])
    customer = H.new_customer()
    if grant_points:
        H.grant_loyalty(customer["id"], grant_points)
    order = H.new_order(customer["id"], order_type=order_type)
    l1 = H.add_line(order["id"], customer["id"], s1["id"], b1["id"], qty1)
    l2 = H.add_line(order["id"], customer["id"], s2["id"], b2["id"], qty2)
    ctx = {"customer": customer, "order": order, "s1": s1, "s2": s2,
           "b1": b1, "b2": b2, "l1": l1, "l2": l2}
    if checkout:
        ctx["order"] = H.checkout(order["id"], customer["id"])
    return ctx


# ==========================================================================
# Queue A — dual_variant_calc / order_total_provisional_vs_final
# ==========================================================================
def test_provisional_total_is_raw_line_sum_before_checkout(api):
    """PRD §3.6: "its computed money and points fields — `total_quantity`,
    `provisional_total_cents`, `discount_cents`, `shipping_fee_cents`, `final_total_cents`,
    `provisional_points`, and `awarded_points` — all begin at zero."
    PRD §3.6: "The provisional total is a raw sum with no discounts and no shipping."

    Design: Difficulty/dual_variant_calc/order_total_provisional_vs_final
    """
    ctx = H.reserved_order(product_type="SOAP", list_price_cents=3000, quantity=1, batch_quantity=100)
    order = H.fetch_order(ctx["order"]["id"])
    assert order["provisional_total_cents"] == 3000
    assert order["discount_cents"] == 0
    assert order["shipping_fee_cents"] == 0
    assert order["final_total_cents"] == 0


def test_final_total_applies_shipping_at_checkout(api):
    """PRD §3.7: "Shipping is then decided against the discounted subtotal: `shipping_fee_cents`
    is zero when the discounted subtotal is at least 5000 cents, and otherwise a flat 800 cents.
    The `final_total_cents` is the discounted subtotal plus `shipping_fee_cents`."

    Design: Difficulty/dual_variant_calc/order_total_provisional_vs_final
    """
    ctx = H.checked_out_order(product_type="SOAP", list_price_cents=3000, quantity=1, batch_quantity=100)
    order = ctx["order"]
    assert order["provisional_total_cents"] == 3000
    assert order["discount_cents"] == 0
    assert order["shipping_fee_cents"] == 800
    assert order["final_total_cents"] == 3800


# ==========================================================================
# Queue A — dual_variant_calc / loyalty_provisional_vs_final_on_recall
# ==========================================================================
def test_provisional_points_posted_over_all_lines_at_checkout(api):
    """PRD §3.7: "The order's `provisional_points` is computed over every line on the order at
    checkout as the sum of the per-line floors of `line_subtotal_cents` divided by 100, and that
    amount is added to the customer's `loyalty_points_balance` immediately."

    Design: Difficulty/dual_variant_calc/loyalty_provisional_vs_final_on_recall
    """
    ctx = _two_line_order(price1=500, price2=300, qty1=10, qty2=10)
    # floor(5000/100) + floor(3000/100) = 50 + 30 = 80.
    assert ctx["order"]["provisional_points"] == 80
    assert H.fetch_customer(ctx["customer"]["id"])["loyalty_points_balance"] == 80


def test_awarded_points_excludes_recall_voided_line(api, merchops_headers):
    """PRD §3.10: "the customer's `loyalty_points_balance` is reduced by the sum, over the voided
    lines, of the floor of each voided line's `line_subtotal_cents` divided by 100."
    PRD §3.7: "`awarded_points` is set to the sum of the per-line floors of `line_subtotal_cents`
    divided by 100 over the lines that are still active (that is, the `SHIPPED` lines, excluding
    any voided by a recall between checkout and delivery)."

    Design: Difficulty/dual_variant_calc/loyalty_provisional_vs_final_on_recall
    """
    ctx = _two_line_order(price1=500, price2=300, qty1=10, qty2=10)
    H.validate_success(api.recall_batch(ctx["b1"]["id"], merchops_headers), 200)  # voids L1 (5000)
    H.fulfill(ctx["order"]["id"])
    order = H.fetch_order(ctx["order"]["id"])
    assert order["awarded_points"] == 30  # only L2 (3000) survives
    assert H.fetch_order_line(ctx["l1"]["id"])["status"] == "VOIDED_RECALL"
    assert H.fetch_customer(ctx["customer"]["id"])["loyalty_points_balance"] == 30


# ==========================================================================
# Queue A — combinatorial_formula / final_pricing_bulk_loyalty_cap
# ==========================================================================
def test_combined_discount_capped_at_max(api):
    """PRD §3.7: "A bulk-quantity discount rate is chosen from `total_quantity`: zero when fewer
    than 50 units, 10 percent when at least 50 and fewer than 100 units, and 20 percent when 100
    units or more."
    PRD §3.7: "otherwise `BRONZE` takes zero, `SILVER` takes 5 percent, and `GOLD` takes 10
    percent."
    PRD §3.7: "The two rates are added, then capped at a combined maximum of 25 percent. The
    `discount_cents` is that combined rate applied to the subtotal, rounded half up to whole
    cents."

    Design: Difficulty/combinatorial_formula/final_pricing_bulk_loyalty_cap
    """
    ctx = H.checked_out_order(product_type="SOAP", list_price_cents=100, quantity=100,
                              batch_quantity=200, order_type="RETAIL", grant_points=2000)
    order = ctx["order"]
    assert H.fetch_customer(ctx["customer"]["id"])["loyalty_tier"] == "GOLD"
    assert order["total_quantity"] == 100
    # 0.20 (bulk) + 0.10 (GOLD) = 0.30, capped to 0.25; 10000 * 0.25 = 2500 (not 3000).
    assert order["discount_cents"] == 2500


def test_capped_discount_yields_free_shipping_final(api):
    """PRD §3.7: "Shipping is then decided against the discounted subtotal: `shipping_fee_cents`
    is zero when the discounted subtotal is at least 5000 cents, and otherwise a flat 800 cents.
    The `final_total_cents` is the discounted subtotal plus `shipping_fee_cents`."

    Design: Difficulty/combinatorial_formula/final_pricing_bulk_loyalty_cap
    """
    ctx = H.checked_out_order(product_type="SOAP", list_price_cents=100, quantity=100,
                              batch_quantity=200, order_type="RETAIL", grant_points=2000)
    order = ctx["order"]
    assert order["shipping_fee_cents"] == 0
    assert order["final_total_cents"] == 7500  # 10000 - 2500 discount, free ship


# ==========================================================================
# Queue A — combinatorial_formula / loyalty_floor_per_line_then_sum
# ==========================================================================
def test_provisional_points_floor_applied_per_line(api):
    """PRD §2.5: "each qualifying line contributes the floor of its own subtotal-in-cents divided
    by 100, and those per-line floors are summed. The floor is applied **per line and then
    summed** — never by flooring a combined subtotal — so that the rounding behavior is
    independent of how a cart is split across lines."

    Design: Difficulty/combinatorial_formula/loyalty_floor_per_line_then_sum
    """
    ctx = _two_line_order(price1=250, price2=250, qty1=1, qty2=1)
    # floor(250/100) + floor(250/100) = 2 + 2 = 4, NOT floor(500/100) = 5.
    assert ctx["order"]["provisional_points"] == 4


def test_awarded_points_floor_applied_per_line(api):
    """PRD §3.7: "`awarded_points` is set to the sum of the per-line floors of
    `line_subtotal_cents` divided by 100 over the lines that are still active".

    Design: Difficulty/combinatorial_formula/loyalty_floor_per_line_then_sum
    """
    ctx = _two_line_order(price1=250, price2=250, qty1=1, qty2=1)
    H.fulfill(ctx["order"]["id"])
    assert H.fetch_order(ctx["order"]["id"])["awarded_points"] == 4


# ==========================================================================
# Queue A — compensating_invariant / loyalty_points_conservation_deliver_return
# ==========================================================================
def test_return_settle_restores_pre_order_balance(api, merchops_headers):
    """PRD §3.8: "Settlement sets `refund_amount_cents` equal to the order's `final_total_cents`,
    sets `revoked_points` equal to the order's `awarded_points`, and reduces the customer's
    `loyalty_points_balance` by that same `awarded_points`, revoking the delivery credit."

    Design: Difficulty/compensating_invariant/loyalty_points_conservation_deliver_return
    """
    ctx = H.approved_return(product_type="SOAP", list_price_cents=3000, quantity=1, grant_points=2000)
    settled = H.validate_success(api.settle_return(ctx["ret"]["id"], merchops_headers), 200)
    assert settled["status"] == "REFUNDED"
    assert settled["revoked_points"] == 30
    # grant 2000 -> checkout +30 -> settle -30 -> back to 2000.
    assert H.fetch_customer(ctx["customer"]["id"])["loyalty_points_balance"] == 2000


def test_return_settle_moves_order_to_returned_refunded(api, merchops_headers):
    """PRD §3.8: "moves the return `APPROVED → REFUNDED`, and in the same step transitions the
    order `fulfillment=DELIVERED → fulfillment=RETURNED` and `payment → REFUNDED`."

    Design: Difficulty/compensating_invariant/loyalty_points_conservation_deliver_return
    """
    ctx = H.approved_return(product_type="SOAP", list_price_cents=3000, quantity=1, grant_points=2000)
    H.validate_success(api.settle_return(ctx["ret"]["id"], merchops_headers), 200)
    order = H.fetch_order(ctx["order"]["id"])
    assert order["fulfillment_status"] == "RETURNED"
    assert order["payment_status"] == "REFUNDED"


# ==========================================================================
# Queue B — calculations: tier + free-ship boundaries
# ==========================================================================
def test_loyalty_tier_silver_at_lower_boundary_500(api, admin_headers):
    """PRD §3.5: "A customer's `loyalty_tier` is computed from the running balance: `BRONZE` while
    the balance is below 500 points, `SILVER` while the balance is at least 500 and below 2000,
    and `GOLD` once the balance is at least 2000."

    Design: Corner/calculations/loyalty_tier_silver_lower_boundary_500
    """
    customer = H.new_customer()
    H.grant_loyalty(customer["id"], 500)
    fetched = H.validate_success(api.get_customer(customer["id"], admin_headers), 200)
    assert fetched["loyalty_points_balance"] == 500
    assert fetched["loyalty_tier"] == "SILVER"


def test_free_ship_at_exact_threshold_5000(api):
    """PRD §3.7: "`shipping_fee_cents` is zero when the discounted subtotal is at least 5000
    cents, and otherwise a flat 800 cents."

    Design: Corner/calculations/free_ship_threshold_exact_boundary_5000
    """
    ctx = H.checked_out_order(product_type="SOAP", list_price_cents=5000, quantity=1, batch_quantity=10)
    order = ctx["order"]
    assert order["discount_cents"] == 0
    assert order["shipping_fee_cents"] == 0
    assert order["final_total_cents"] == 5000
