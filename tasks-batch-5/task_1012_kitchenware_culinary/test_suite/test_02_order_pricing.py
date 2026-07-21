"""Order pricing and loyalty-point accrual: provisional-vs-final variants, the
tier-discount cap, per-line points rounding, and per-jurisdiction tax."""
from test_helpers import (
    validate_success,
    make_store, make_sku, make_member, make_order, pay_order, fulfill_order,
    set_clock, order_line,
)


def _build_ca_two_sku_order(api):
    """CA store, STANDARD member, skuA list 10000 (qty2) + skuB list 5000 (qty1)."""
    set_clock("2026-07-05T00:00:00Z")
    store = make_store(state_code="CA", name="SF Store")
    sku_a = make_sku(list_price_cents=10000, on_hand_qty=10, category="COOKWARE", name="Dutch Oven")
    sku_b = make_sku(list_price_cents=5000, on_hand_qty=10, category="COOKWARE", name="Whisk")
    member = make_member(store["id"])
    order = make_order(member["id"], store["id"],
                       [order_line(sku_a["id"], 2), order_line(sku_b["id"], 1)])
    return store, member, order


# ── dual_variant_calc / order_total_provisional_vs_final ──────
def test_provisional_total_covers_all_lines(api):
    """PRD §3.3: "These figures are provisional because they cover every ordered line,
    some of which may later be excluded at fulfillment."
    PRD §3.3: "The `total_cents` is the subtotal minus the tier discount plus the tax."

    Design: Difficulty/dual_variant_calc/order_total_provisional_vs_final
    """
    store, member, order = _build_ca_two_sku_order(api)
    # subtotal 25000; STANDARD discount 0; CA tax round(25000*0.0875)=2188; total 27188.
    assert order["subtotal_cents"] == 25000
    assert order["total_cents"] == 27188
    assert order["pending_points"] == 250  # 200 (line A) + 50 (line B), round per line


def test_final_total_over_fulfilled_lines_only(api):
    """PRD §3.3: "The order's subtotal, tax, and total are then recomputed in their final
    form, but this time over the fulfilled lines only, so void lines drop out and the final
    subtotal, tax, and total generally differ from the provisional figures."

    Design: Difficulty/dual_variant_calc/order_total_provisional_vs_final
    """
    store, member, order = _build_ca_two_sku_order(api)
    line_b = order["lines"][1]["line_id"]
    pay_order(order["id"])
    final = fulfill_order(order["id"], exclude_line_ids=[line_b])
    # FULFILLED lines = A only: subtotal 20000; CA tax round(20000*0.0875)=1750; total 21750.
    assert final["subtotal_cents"] == 20000
    assert final["total_cents"] == 21750
    assert final["earned_points"] == 200  # 10000*2/100*1.00, over FULFILLED line A only


# ── dual_variant_calc / loyalty_points_pending_vs_earned ──────
def _build_or_two_sku_order(api):
    store = make_store(state_code="OR", name="PDX Store")
    sku_a = make_sku(list_price_cents=30000, on_hand_qty=5, category="APPLIANCE", name="Stand Mixer")
    sku_b = make_sku(list_price_cents=10000, on_hand_qty=5, category="COFFEE", name="Kettle")
    member = make_member(store["id"])
    order = make_order(member["id"], store["id"],
                       [order_line(sku_a["id"], 1), order_line(sku_b["id"], 1)],
                       fulfillment_type="SHIP_FROM_STORE")
    return store, member, order


def test_member_pending_points_accrue_over_all_lines_at_create(api):
    """PRD §3.3: "The `pending_points` bucket holds provisional points from orders that
    are reserved but not yet fulfilled".
    PRD §3.3: "The system then computes the provisional pricing over all lines and the
    provisional points, and adds the order's pending points to the member's pending-points
    balance."

    Design: Difficulty/dual_variant_calc/loyalty_points_pending_vs_earned
    """
    store, member, order = _build_or_two_sku_order(api)
    # pending points: 30000/100*1.00=300 + 10000/100*1.00=100 = 400.
    assert order["pending_points"] == 400
    member_after = validate_success(api.get_member(member["id"], _admin()), 200)
    assert member_after["pending_points"] == 400


def test_member_earned_points_post_over_fulfilled_lines_only(api):
    """PRD §3.3: "the order's earned points are added to the member's earned-points balance,
    and the order's pending points are subtracted from the member's pending-points balance."
    PRD §2.9 / §3.3: earned points are "computed over the fulfilled lines using the same
    per-line, round-then-sum discipline".

    Design: Difficulty/dual_variant_calc/loyalty_points_pending_vs_earned
    """
    store, member, order = _build_or_two_sku_order(api)
    line_b = order["lines"][1]["line_id"]
    pay_order(order["id"])
    final = fulfill_order(order["id"], exclude_line_ids=[line_b])
    assert final["earned_points"] == 300     # only fulfilled line A: 30000/100*1.00
    assert final["pending_points"] == 400    # order's provisional figure is retained
    member_after = validate_success(api.get_member(member["id"], _admin()), 200)
    assert member_after["earned_points"] == 300
    assert member_after["pending_points"] == 0


# ── combinatorial_formula / order_total_tiered_discount_cap ───
def _build_silver_member_big_order(api):
    """OR store; member reaches SILVER by fulfilling a 50000 order, then a 500000 order."""
    store = make_store(state_code="OR", name="OR Store")
    sku_big = make_sku(list_price_cents=50000, on_hand_qty=20, category="COOKWARE", name="Copper Set")
    member = make_member(store["id"])
    o1 = make_order(member["id"], store["id"], [order_line(sku_big["id"], 1)], fulfillment_type="IN_STORE")
    pay_order(o1["id"])
    fulfill_order(o1["id"])  # annual_spend 50000 -> SILVER
    o2 = make_order(member["id"], store["id"], [order_line(sku_big["id"], 10)], fulfillment_type="IN_STORE")
    return store, member, o2


def test_second_order_prices_at_silver_snapshot(api):
    """PRD §3.3: "The order snapshots the member's current tier into `tier_at_pricing`,
    which thereafter drives both the discount and the points multiplier for this order."
    PRD §3.3: "The order's `subtotal_cents` is the sum, over every line, of that line's
    unit price multiplied by its quantity."

    Design: Difficulty/combinatorial_formula/order_total_tiered_discount_cap
    """
    store, member, o2 = _build_silver_member_big_order(api)
    assert o2["tier_at_pricing"] == "SILVER"
    assert o2["subtotal_cents"] == 500000


def test_tier_discount_capped_at_20000(api):
    """PRD §3.3: "The `tier_discount_cents` is that percentage of the subtotal, rounded
    half up to whole cents, then capped so it never exceeds 20,000 cents."

    Design: Difficulty/combinatorial_formula/order_total_tiered_discount_cap
    """
    store, member, o2 = _build_silver_member_big_order(api)
    # raw 5% of 500000 = 25000 -> capped to 20000; OR tax 0; total 500000-20000 = 480000.
    assert o2["tier_discount_cents"] == 20000
    assert o2["total_cents"] == 480000


# ── combinatorial_formula / loyalty_points_per_line_rounding ──
def _build_per_line_rounding_order(api):
    store = make_store(state_code="CA", name="LA Store")
    sku_x = make_sku(list_price_cents=1050, on_hand_qty=5, category="KNIVES", name="Paring Knife")
    sku_y = make_sku(list_price_cents=2050, on_hand_qty=5, category="KNIVES", name="Peeler")
    member = make_member(store["id"])
    order = make_order(member["id"], store["id"],
                       [order_line(sku_x["id"], 1), order_line(sku_y["id"], 1)])
    return order


def test_points_rounded_per_line_before_summation(api):
    """PRD §2.7: "In loyalty points accrual, rounding is applied **per line, before the
    lines are summed** — each line's point contribution is rounded to a whole number and
    only then are the per-line results added together."

    Design: Difficulty/combinatorial_formula/loyalty_points_per_line_rounding
    """
    order = _build_per_line_rounding_order(api)
    assert order["subtotal_cents"] == 3100
    # round(10.5)=11 + round(20.5)=21 = 32 (per line), not round(31.0)=31 (sum-then-round).
    assert order["pending_points"] == 32


def test_per_line_rounding_diverges_from_sum_then_round(api):
    """PRD §2.7: "Summing raw fractional contributions and rounding once at the end is
    incorrect and would produce different totals."

    Design: Difficulty/combinatorial_formula/loyalty_points_per_line_rounding
    """
    order = _build_per_line_rounding_order(api)
    assert order["pending_points"] == 32
    assert order["pending_points"] != 31, "sum-then-round (31) is the wrong discipline"


# ── Corner/calculations/order_tax_by_state_ny ─────────────────
def test_order_tax_at_ny_store(api):
    """PRD §3.3: "The tax rate is determined by the fulfilling store's jurisdiction: 8.75%
    for `CA`, 0% for `OR`, and 8% for `NY`."

    Design: Corner/calculations/order_tax_by_state_ny
    """
    store = make_store(state_code="NY", name="NY Store")
    sku = make_sku(list_price_cents=10000, on_hand_qty=5, category="COOKWARE", name="Roaster")
    member = make_member(store["id"])
    order = make_order(member["id"], store["id"], [order_line(sku["id"], 1)], fulfillment_type="IN_STORE")
    # STANDARD subtotal 10000; NY tax round(10000*0.08)=800; total 10800.
    assert order["tax_cents"] == 800
    assert order["total_cents"] == 10800


def _admin():
    from test_helpers import TEST_USERS
    return TEST_USERS["admin_headers"]
