"""Provisional-vs-final pricing, estimated-vs-settled points, and the
redeem/cancel conservation invariant.

Queue A (Difficulty): dual_variant_calc, compensating_invariant (loyalty).
"""
from test_helpers import (
    validate_success,
    get_success_data,
    fixtures as fx,
    factories as fac,
)


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / order_total_provisional_vs_final
# ---------------------------------------------------------------------------
def test_provisional_total_at_creation(api, sm):
    """PRD 3.3: "In the **provisional** variant written at creation,
    `redeemed_points` is treated as zero (no redemption has yet been applied)
    and the discount uses the member's tier and subscription as they stand at
    creation."

    Design: Difficulty/dual_variant_calc/order_total_provisional_vs_final
    """
    member = fx.create_member()
    fx.grant_points(member["id"], 5000)
    product = fx.create_product(category="SHOE", unit_price_cents=12000, initial_stock=3)
    order = fx.create_single_line_order(member["id"], product["id"], 1)
    # No discount (STANDARD, no sub); redeemed forced 0; shipping 0 (12000>=7500).
    assert order["provisional_total_cents"] == 12000


def test_final_total_at_capture_with_redemption(api, sm):
    """PRD 3.4: "Capturing payment moves it from `AUTHORIZED` to `PAID`; at
    capture the order's total is recomputed in the **final** variant and written
    to both `final_total_cents` and `net_paid_cents`. The final variant differs
    from the provisional one in two ways: the redemption actually applied is now
    included, and the discount is recomputed against the member's tier and
    subscription as they stand at that moment, which may differ from creation."

    Design: Difficulty/dual_variant_calc/order_total_provisional_vs_final
    """
    member = fx.create_member()
    fx.grant_points(member["id"], 5000)
    product = fx.create_product(category="SHOE", unit_price_cents=12000, initial_stock=3)
    order = fx.create_single_line_order(member["id"], product["id"], 1)
    oid = order["id"]
    get_success_data(api.apply_redemption(oid, {"points_to_redeem": 5000}, sm))
    get_success_data(api.authorize_payment(oid, sm))
    captured = validate_success(api.capture_payment(oid, sm), 200)
    # 12000 - 5000 redemption + 0 shipping = 7000; provisional stays 12000.
    assert captured["final_total_cents"] == 7000
    assert captured["net_paid_cents"] == 7000
    assert captured["provisional_total_cents"] == 12000


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / loyalty_points_estimated_vs_settled_net_of_return
# ---------------------------------------------------------------------------
def _fulfilled_two_line_order(member):
    pa = fx.create_product(category="SHOE", unit_price_cents=10000, initial_stock=3)
    pb = fx.create_product(category="NUTRITION", unit_price_cents=5000, initial_stock=3)
    order = fx.create_order(member["id"], [fac.line(pa["id"], 1), fac.line(pb["id"], 1)])
    return pa, pb, order


def test_estimated_points_at_creation(api, sm):
    """PRD 3.3: "Order creation also projects **estimated loyalty points**
    (`estimated_points_earned`)."
    PRD 3.3: "The estimate sums the rounded per-line figures across every line,
    using the tier as of creation."

    Design: Difficulty/dual_variant_calc/loyalty_points_estimated_vs_settled_net_of_return
    """
    member = fx.create_member()
    _pa, _pb, order = _fulfilled_two_line_order(member)
    # SHOE 10000 -> 1000 pts; NUTRITION 5000 -> 500 pts; estimate 1500 (STANDARD).
    assert order["estimated_points_earned"] == 1500


def test_settled_points_net_of_return(api, sm):
    """PRD 3.4: "settled loyalty points are computed and added to the member's
    `loyalty_points_balance` with each line's `line_points_earned` recorded"
    PRD 3.5: "the member's `loyalty_points_balance` is reduced by that returned
    line's `line_points_earned`, reversing the points that line originally earned."

    Design: Difficulty/dual_variant_calc/loyalty_points_estimated_vs_settled_net_of_return
    """
    member = fx.create_member()
    pa = fx.create_product(category="SHOE", unit_price_cents=10000, initial_stock=3)
    pb = fx.create_product(category="NUTRITION", unit_price_cents=5000, initial_stock=3)
    order = fx.create_fulfilled_order(
        member["id"], [fac.line(pa["id"], 1), fac.line(pb["id"], 1)]
    )
    shoe_line = fx.get_first_order_line(order["id"], product_id=pa["id"])
    ret = fx.open_inspected_return(shoe_line["id"])
    get_success_data(api.approve_return(ret["id"], sm))
    member_after = fx.get_member(member["id"])
    # Settled 1500, minus reversed SHOE line 1000 -> 500.
    assert member_after["loyalty_points_balance"] == 500


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / loyalty_points_redeem_then_cancel_conserved
# ---------------------------------------------------------------------------
def test_redeem_debits_balance_immediately(api, sm):
    """PRD 3.4: "the member's `loyalty_points_balance` is debited by
    `points_to_redeem` immediately — the points leave the balance at redemption
    time, not at payment."

    Design: Difficulty/compensating_invariant/loyalty_points_redeem_then_cancel_conserved
    """
    member = fx.create_member()
    fx.grant_points(member["id"], 5000)
    product = fx.create_product(category="GEAR", unit_price_cents=12000, initial_stock=3)
    order = fx.create_single_line_order(member["id"], product["id"], 1)
    get_success_data(api.apply_redemption(order["id"], {"points_to_redeem": 5000}, sm))
    assert fx.get_member(member["id"])["loyalty_points_balance"] == 0


def test_redeem_then_cancel_conserves_balance(api, sm):
    """PRD 3.4: "If the order carried a redemption (`redeemed_points` greater
    than zero), those points are returned to the member's `loyalty_points_balance`
    as a redeem reversal."

    Design: Difficulty/compensating_invariant/loyalty_points_redeem_then_cancel_conserved
    """
    member = fx.create_member()
    fx.grant_points(member["id"], 5000)
    product = fx.create_product(category="GEAR", unit_price_cents=12000, initial_stock=3)
    order = fx.create_single_line_order(member["id"], product["id"], 1)
    get_success_data(api.apply_redemption(order["id"], {"points_to_redeem": 5000}, sm))
    get_success_data(api.cancel_order(order["id"], sm))
    # Reversal restores the pre-redemption balance of 5000.
    assert fx.get_member(member["id"])["loyalty_points_balance"] == 5000
