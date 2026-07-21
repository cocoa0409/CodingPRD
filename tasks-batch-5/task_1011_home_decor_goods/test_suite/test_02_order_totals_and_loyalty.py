"""Order totals (per-line rounding, tier discount), the provisional-vs-earned
points split, and loyalty points conservation."""
from test_helpers import (
    validate_success, set_clock, new_store, new_product, new_inventory,
    new_member, new_order, add_line, capture, ready, fulfill, cancel_order,
    api_client, TEST_USERS,
)

ASSOCIATE = TEST_USERS["associate_headers"]


# ─── order_subtotal_round_per_line_then_sum (queue A) ───

def _two_line_gold_order():
    set_clock("2026-07-01T00:00:00Z")
    store = new_store(name="Store C1", region_code="NY")
    pa = new_product(sku="SKU-CA", name="Frame A", category="DECOR",
                     base_price_cents=1055, clearance_floor_cents=100,
                     first_received_at="2026-06-25T00:00:00Z")
    pb = new_product(sku="SKU-CB", name="Frame B", category="DECOR",
                     base_price_cents=1055, clearance_floor_cents=100,
                     first_received_at="2026-06-25T00:00:00Z")
    new_inventory(store["id"], pa["id"], 5)
    new_inventory(store["id"], pb["id"], 5)
    member = new_member(email="c1@x.com", full_name="C One", initial_lifetime_spend_cents=200000)
    order = new_order(store["id"], "CARRYOUT", member_id=member["id"])
    la = add_line(order["id"], pa["id"], 1)
    lb = add_line(order["id"], pb["id"], 1)
    return order, la, lb


def test_gold_lines_round_half_up_per_line():
    """PRD §3.4: "For each line, `line_net_cents` is the snapshotted unit price
    times the quantity, reduced by the tier discount percentage, rounded to a whole
    cent half-up."

    Design: Difficulty/combinatorial_formula/order_subtotal_round_per_line_then_sum
    """
    _, la, lb = _two_line_gold_order()
    assert la["line_net_cents"] == 950, f"expected 950, got {la['line_net_cents']}"
    assert lb["line_net_cents"] == 950, f"expected 950, got {lb['line_net_cents']}"


def test_subtotal_sums_rounded_lines_not_rounded_sum():
    """PRD §3.4: "The order's `subtotal_cents` is the sum of the per-line net
    amounts — and rounding is applied per line first, then the rounded line amounts
    are summed, never the other way around."

    Design: Difficulty/combinatorial_formula/order_subtotal_round_per_line_then_sum
    """
    order, _, _ = _two_line_gold_order()
    data = validate_success(api_client.get_order(order["id"], ASSOCIATE))
    assert data["subtotal_cents"] == 1900, (
        f"per-line rounding must yield 1900 (not the 1899 of sum-then-round), "
        f"got {data['subtotal_cents']}")


# ─── loyalty_points_provisional_vs_earned (queue A) ───

def _gold_bopis_redeem_order():
    set_clock("2026-07-01T00:00:00Z")
    store = new_store(name="Store P1")
    product = new_product(sku="SKU-P1", name="Throw Pillow", category="TEXTILE",
                          base_price_cents=1000, clearance_floor_cents=100,
                          first_received_at="2026-06-25T00:00:00Z")
    new_inventory(store["id"], product["id"], 10)
    member = new_member(email="p1@x.com", full_name="P One",
                        initial_lifetime_spend_cents=200000, initial_points_balance=1000)
    order = new_order(store["id"], "BOPIS", member_id=member["id"], requested_redeem_points=500)
    add_line(order["id"], product["id"], 2)
    return store, product, member, order


def test_provisional_points_over_pre_redemption_subtotal():
    """PRD §3.4: "The `provisional_points` is an estimate computed at creation over
    the pre-redemption subtotal: the whole-dollar count of `subtotal_cents` (its
    value divided by 100, floored) multiplied by the member's tier rate — 1 point
    per dollar for `STANDARD`, 2 for `SILVER`, and 3 for `GOLD`."
    PRD §3.4: "The `total_due_cents` is the subtotal minus the redeemed amount,
    floored at zero."

    Design: Difficulty/dual_variant_calc/loyalty_points_provisional_vs_earned
    """
    _, _, _, order = _gold_bopis_redeem_order()
    data = validate_success(api_client.get_order(order["id"], ASSOCIATE))
    assert data["subtotal_cents"] == 1800, f"expected subtotal 1800, got {data['subtotal_cents']}"
    assert data["total_due_cents"] == 1300, f"expected total_due 1300, got {data['total_due_cents']}"
    assert data["provisional_points"] == 54, f"expected provisional 54, got {data['provisional_points']}"


def test_earned_points_over_post_redemption_total_credited_on_fulfill():
    """PRD §3.4: "The `earned_points` is computed the same way but over the
    post-redemption `total_due_cents`, and it is the figure actually credited on
    fulfilment; because it is measured after redemption, it diverges from the
    provisional estimate whenever any points were redeemed."
    PRD §3.4: "the member's `earned_points` are credited to `points_balance` and
    added to `points_earned_total`".

    Design: Difficulty/dual_variant_calc/loyalty_points_provisional_vs_earned
    """
    _, _, member, order = _gold_bopis_redeem_order()
    capture(order["id"])
    ready(order["id"])
    fulfilled = fulfill(order["id"])
    assert fulfilled["earned_points"] == 39, f"expected earned 39, got {fulfilled['earned_points']}"
    m = validate_success(api_client.get_loyalty_member(member["id"], ASSOCIATE))
    # 1000 seeded − 500 redeemed at create + 39 earned at fulfil = 539.
    assert m["points_balance"] == 539, f"expected balance 539, got {m['points_balance']}"


# ─── silver_tier_discount_on_order_line (queue B) ───

def test_silver_member_gets_five_percent_line_discount():
    """PRD §3.3: "A member is `STANDARD` while lifetime spend is below 50,000
    cents; `SILVER` once lifetime spend is at least 50,000 cents but below 200,000
    cents; and `GOLD` once lifetime spend reaches 200,000 cents or more."
    PRD §3.4: "The member's tier sets a checkout discount percentage,
    `tier_discount_pct`: zero for `STANDARD`, 5% for `SILVER`, and 10% for `GOLD`".

    Design: Corner/calculations/silver_tier_discount_on_order_line
    """
    set_clock("2026-07-01T00:00:00Z")
    store = new_store(name="Store CA2", region_code="NY")
    product = new_product(sku="SKU-CA2", name="Napkin Set", category="TEXTILE",
                          base_price_cents=1000, clearance_floor_cents=100,
                          first_received_at="2026-06-25T00:00:00Z")
    new_inventory(store["id"], product["id"], 5)
    member = new_member(email="ca2@x.com", full_name="CA Two", initial_lifetime_spend_cents=60000)
    assert member["tier"] == "SILVER", f"expected SILVER, got {member['tier']}"
    order = new_order(store["id"], "CARRYOUT", member_id=member["id"])
    line = add_line(order["id"], product["id"], 2)
    assert line["line_net_cents"] == 1900, f"expected 1900, got {line['line_net_cents']}"
    data = validate_success(api_client.get_order(order["id"], ASSOCIATE))
    assert data["subtotal_cents"] == 1900, f"expected subtotal 1900, got {data['subtotal_cents']}"


# ─── loyalty_points_conserved_redeem_then_cancel (queue A) ───

def _redeemed_then_cancelled_member():
    store = new_store(name="Store CI2")
    member = new_member(email="ci2@x.com", full_name="CI Two", initial_points_balance=1000)
    order = new_order(store["id"], "CARRYOUT", member_id=member["id"], requested_redeem_points=500)
    cancel_order(order["id"])
    return member


def test_points_balance_restored_after_cancel():
    """PRD §2.7: "Redeeming on an order decreases the balance and increases the
    redeemed total; cancelling that order restores the balance and decreases the
    redeemed total".
    PRD §3.5: "Cancellation also restores loyalty: the order's `redeemed_cents` are
    added back to the member's `points_balance` and subtracted from
    `points_redeemed_total`."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_redeem_then_cancel
    """
    member = _redeemed_then_cancelled_member()
    m = validate_success(api_client.get_loyalty_member(member["id"], ASSOCIATE))
    assert m["points_balance"] == 1000, f"expected balance restored to 1000, got {m['points_balance']}"


def test_points_redeemed_total_zeroed_after_cancel():
    """PRD §2.7: "the redeemable balance always equals the lifetime points earned
    minus the lifetime points redeemed: `points_balance` equals `points_earned_total`
    minus `points_redeemed_total`."
    PRD §3.5: "Cancellation also restores loyalty: the order's `redeemed_cents` are
    added back to the member's `points_balance` and subtracted from
    `points_redeemed_total`."

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_redeem_then_cancel
    """
    member = _redeemed_then_cancelled_member()
    m = validate_success(api_client.get_loyalty_member(member["id"], ASSOCIATE))
    assert m["points_redeemed_total"] == 0, (
        f"expected points_redeemed_total 0 after cancel, got {m['points_redeemed_total']}")
