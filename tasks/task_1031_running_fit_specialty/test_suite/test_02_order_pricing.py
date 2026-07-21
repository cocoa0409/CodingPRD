"""Discount stacking, per-line points rounding, and shipping thresholds.

Queue A (Difficulty): combinatorial_formula.
Queue B (Corner): calculations (shipping, promo gating).
"""
from test_helpers import (
    validate_success,
    fixtures as fx,
    factories as fac,
)


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / discount_stack_cap_and_total_ceiling_mode_a
# ---------------------------------------------------------------------------
def test_discount_stack_cap_and_ceiling_pct(api, sm):
    """PRD 3.3: "The subscription and loyalty components are added together to
    form a member base, and that base is capped at 0.12 — the member stack may
    never exceed twelve percent."
    PRD 3.3: "only if the promotional component is greater than zero **and**
    `subtotal_cents` is at least 5000 cents is the promo added on top of the
    capped member stack, with the combined result capped at a hard ceiling of 0.20."

    Design: Difficulty/combinatorial_formula/discount_stack_cap_and_total_ceiling_mode_a
    """
    member = fx.create_member()
    fx.create_subscription(member["id"], "ELITE")
    product = fx.create_product(category="GEAR", unit_price_cents=10000, initial_stock=3)
    order = fx.create_order(member["id"], [fac.line(product["id"], 1)], promo_code="SPRING15")
    assert order["discount_pct_applied"] == 0.20


def test_discount_stack_cap_and_ceiling_cents_and_total(api, sm):
    """PRD 3.3: "`discount_cents` is computed as `subtotal_cents` multiplied by
    `discount_pct_applied`, rounded half up to whole cents at this single point"
    PRD 3.3: "`shipping_fee_cents` is zero when `subtotal_after_discount` is at
    least 7500 cents, and 599 cents otherwise."

    Design: Difficulty/combinatorial_formula/discount_stack_cap_and_total_ceiling_mode_a
    """
    member = fx.create_member()
    fx.create_subscription(member["id"], "ELITE")
    product = fx.create_product(category="GEAR", unit_price_cents=10000, initial_stock=3)
    order = fx.create_order(member["id"], [fac.line(product["id"], 1)], promo_code="SPRING15")
    # subtotal 10000 * 0.20 = 2000 discount; subtotal_after 8000 (>=7500) -> free ship.
    assert order["discount_cents"] == 2000
    assert order["provisional_total_cents"] == 8000


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / loyalty_points_round_per_line_then_sum_mode_b
# ---------------------------------------------------------------------------
def test_points_round_per_line_then_sum_estimated(api, sm):
    """PRD 3.3: "Points are computed per line and then summed — never by summing
    dollars and rounding once."
    PRD 3.3: "The estimate sums the rounded per-line figures across every line,
    using the tier as of creation."

    Design: Difficulty/combinatorial_formula/loyalty_points_round_per_line_then_sum_mode_b
    """
    member = fx.create_member()
    pa = fx.create_product(category="APPAREL", unit_price_cents=1005, initial_stock=3)
    pb = fx.create_product(category="APPAREL", unit_price_cents=1005, initial_stock=3)
    order = fx.create_order(
        member["id"], [fac.line(pa["id"], 1), fac.line(pb["id"], 1)]
    )
    # round_half_up(100.5)=101 per line; 101+101=202. Sum-then-round would be 201.
    assert order["estimated_points_earned"] == 202


def test_points_round_per_line_each_line_value(api, sm):
    """PRD 3.3: "round that line result half up to a whole number; store it as
    the line's `line_points_earned`."

    Design: Difficulty/combinatorial_formula/loyalty_points_round_per_line_then_sum_mode_b
    """
    member = fx.create_member()
    pa = fx.create_product(category="APPAREL", unit_price_cents=1005, initial_stock=3)
    pb = fx.create_product(category="APPAREL", unit_price_cents=1005, initial_stock=3)
    order = fx.create_order(
        member["id"], [fac.line(pa["id"], 1), fac.line(pb["id"], 1)]
    )
    lines = fx.get_success_data(
        api.list_order_lines(sm, params={"order_id": order["id"]})
    )
    assert len(lines) == 2
    for line in lines:
        assert line["line_points_earned"] == 101


# ---------------------------------------------------------------------------
# Corner: calculations
# ---------------------------------------------------------------------------
def test_free_shipping_at_threshold(api, sm):
    """PRD 3.3: "`shipping_fee_cents` is zero when `subtotal_after_discount` is
    at least 7500 cents, and 599 cents otherwise."

    Design: Corner/calculations/c_free_shipping_at_threshold
    """
    member = fx.create_member()
    product = fx.create_product(category="GEAR", unit_price_cents=7500, initial_stock=3)
    order = fx.create_single_line_order(member["id"], product["id"], 1)
    assert order["shipping_fee_cents"] == 0
    assert order["provisional_total_cents"] == 7500


def test_free_shipping_below_threshold(api, sm):
    """PRD 3.3: "`shipping_fee_cents` is zero when `subtotal_after_discount` is
    at least 7500 cents, and 599 cents otherwise."

    Design: Corner/calculations/c_free_shipping_below_threshold
    """
    member = fx.create_member()
    product = fx.create_product(category="GEAR", unit_price_cents=7499, initial_stock=3)
    order = fx.create_single_line_order(member["id"], product["id"], 1)
    assert order["shipping_fee_cents"] == 599
    assert order["provisional_total_cents"] == 8098


def test_promo_gated_below_min_subtotal(api, sm):
    """PRD 3.3: "only if the promotional component is greater than zero **and**
    `subtotal_cents` is at least 5000 cents is the promo added on top of the
    capped member stack, with the combined result capped at a hard ceiling of 0.20."
    PRD 3.3: "If the promo does not qualify (no promo, unrecognised code, or a
    subtotal below 5000 cents), `discount_pct_applied` is simply the capped
    member stack."

    Design: Corner/calculations/c_promo_gated_below_min_subtotal
    """
    member = fx.create_member()
    fx.create_subscription(member["id"], "ELITE")
    product = fx.create_product(category="GEAR", unit_price_cents=4000, initial_stock=3)
    order = fx.create_order(member["id"], [fac.line(product["id"], 1)], promo_code="SPRING15")
    # base 0.15 -> capped 0.12; promo disabled (subtotal 4000 < 5000).
    assert order["discount_pct_applied"] == 0.12
    assert order["discount_cents"] == 480
    # subtotal_after 3520 (<7500) -> shipping 599; total 4119.
    assert order["provisional_total_cents"] == 4119
