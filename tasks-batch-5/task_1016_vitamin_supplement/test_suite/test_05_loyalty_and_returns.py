"""Loyalty accrual and returns: tiered auto-ship earning, the earn/reverse
conservation across fulfilment and return, tier boundaries, refund variants
(full vs unwanted), and the return-quantity ceiling.
"""
from test_helpers import (
    validate_success, validate_error, TEST_USERS,
    new_customer_with_points, make_customer_headers,
    setup_autoship_draft_order, setup_fulfilled_one_off_order, setup_return_ready,
    refund_return, place, fulfill,
)

OPERATOR = TEST_USERS["store_operator_headers"]


def test_autoship_final_subtotal_uses_cadence_discount(api):
    """PRD §3.6: "for an auto-ship order it is the owning subscription's
    `autoship_discount_pct`; for a one-off order it is the loyalty purchase
    discount for the buyer's tier".

    Design: Difficulty/combinatorial_formula/loyalty_points_earned_tiered_autoship
    """
    ctx = setup_autoship_draft_order(cadence_days=30, quantity_per_cycle=2,
                                     unit_price_cents=5000, lot_quantity=100, tier="GOLD")
    place(ctx["order"]["id"], ctx["customer"]["id"])
    fulfilled = fulfill(ctx["order"]["id"])
    # 30-day autoship discount 0.05: net_unit = round_half_up(5000*0.95)=4750; *2 = 9500.
    assert fulfilled["final_subtotal_cents"] == 9500


def test_autoship_gold_points_earned_capped_multiplier(api):
    """PRD §3.6: "The earn multiplier is the tier multiplier — 1.0 for `BRONZE`,
    1.25 for `SILVER`, 1.5 for `GOLD` — plus an additional 0.25 auto-ship bonus
    when the order is an auto-ship order. The `points_earned` is the base points
    multiplied by the earn multiplier, floored to a whole number, and then capped
    at 2000."

    Design: Difficulty/combinatorial_formula/loyalty_points_earned_tiered_autoship
    """
    ctx = setup_autoship_draft_order(cadence_days=30, quantity_per_cycle=2,
                                     unit_price_cents=5000, lot_quantity=100, tier="GOLD")
    place(ctx["order"]["id"], ctx["customer"]["id"])
    fulfilled = fulfill(ctx["order"]["id"])
    # base = floor(9500/100)=95; multiplier = 1.5 + 0.25 = 1.75; floor(95*1.75)=166.
    assert fulfilled["points_earned"] == 166


def test_fulfilment_credits_points_balance(api):
    """PRD §3.6: "the settled `points_earned` is added to the customer's
    `points_balance` and to `lifetime_points_earned`, and `loyalty_tier` is
    recomputed."

    Design: Difficulty/compensating_invariant/loyalty_points_conservation
    """
    ctx = setup_fulfilled_one_off_order(unit_price_cents=5000, quantity=2, lot_quantity=10)
    cust = validate_success(api.get_customer(ctx["customer"]["id"], OPERATOR), 200)
    # BRONZE: net_unit 5000, final 10000, base floor(10000/100)=100, mult 1.0 -> 100.
    assert cust["points_balance"] == 100


def test_full_return_reverses_all_earned_points(api):
    """PRD §3.7: "On refund, the customer's `points_balance` is decreased by
    `points_reversed` (a compensating claw-back of the earned points)".

    Design: Difficulty/compensating_invariant/loyalty_points_conservation
    """
    ctx = setup_return_ready(reason="DEFECT", unit_price_cents=5000, quantity=2,
                             return_quantity=2, lot_quantity=10, approve=True)
    refund_return(ctx["return_"]["id"])
    cust = validate_success(api.get_customer(ctx["customer"]["id"], OPERATOR), 200)
    # 100 earned at fulfil, 100 reversed by the full-quantity return -> back to 0.
    assert cust["points_balance"] == 0


def test_loyalty_tier_gold_at_exactly_1000(api):
    """PRD §3.3: "The thresholds are inclusive at the boundary — exactly 1000
    lifetime points is `GOLD`, and 999 is `SILVER`."

    Design: Corner/calculations/corner_loyalty_tier_gold_boundary_inclusive
    """
    cust = new_customer_with_points(1000, email="ca1@x.com", full_name="CA One")
    assert cust["loyalty_tier"] == "GOLD"


def test_loyalty_tier_silver_at_999(api):
    """PRD §3.3: "The thresholds are inclusive at the boundary — exactly 1000
    lifetime points is `GOLD`, and 999 is `SILVER`."

    Design: Corner/calculations/corner_loyalty_tier_gold_boundary_below
    """
    cust = new_customer_with_points(999, email="ca2@x.com", full_name="CA Two")
    assert cust["loyalty_tier"] == "SILVER"


def test_unwanted_return_applies_restocking_fee_and_restocks(api):
    """PRD §3.7: "When the reason is `UNWANTED`, the unwanted variant applies:
    `refund_cents` is the gross refund value multiplied by one minus the 0.15
    restocking fee, rounded half-up to a whole cent, and `restock` is true when
    the source lot's `status` is still `AVAILABLE` and false otherwise."

    Design: Difficulty/dual_variant_calc/return_refund_full_vs_unwanted
    """
    ctx = setup_return_ready(reason="UNWANTED", unit_price_cents=5000, quantity=1,
                             return_quantity=1, lot_quantity=10, approve=True)
    refunded = refund_return(ctx["return_"]["id"])
    # gross = 5000; round_half_up(5000 * 0.85) = 4250; lot AVAILABLE -> restock true.
    assert refunded["refund_cents"] == 4250
    assert refunded["restock"] is True


def test_defect_return_refunds_gross_and_does_not_restock(api):
    """PRD §3.7: "When the reason is `DEFECT`, `RECALL`, or `EXPIRED`, the full
    variant applies: `refund_cents` equals the gross refund value with no
    restocking fee, and `restock` is false (the units are not returned to
    inventory)."

    Design: Difficulty/dual_variant_calc/return_refund_full_vs_unwanted
    """
    ctx = setup_return_ready(reason="DEFECT", unit_price_cents=5000, quantity=1,
                             return_quantity=1, lot_quantity=10, approve=True)
    refunded = refund_return(ctx["return_"]["id"])
    # gross = 5000; full variant -> refund 5000, no restock.
    assert refunded["refund_cents"] == 5000
    assert refunded["restock"] is False


def test_return_quantity_exceeding_fulfilled_rejected(api):
    """PRD §3.7: "The returned `quantity` must be at least 1 (else
    `ERR_INVALID_QUANTITY`) and must not exceed the line's fulfilled, non-shorted
    quantity (else `ERR_RETURN_QUANTITY_EXCEEDS`)."

    Design: Corner/validations/corner_return_quantity_exceeds_rejected
    """
    ctx = setup_fulfilled_one_off_order(unit_price_cents=3000, quantity=1, lot_quantity=10)
    res = api.create_return(
        {"order_id": ctx["order"]["id"], "order_line_id": ctx["line"]["id"],
         "quantity": 5, "reason": "UNWANTED"},
        make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, "ERR_RETURN_QUANTITY_EXCEEDS", expected_status=422)
