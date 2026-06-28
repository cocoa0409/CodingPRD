"""Checkout settlement, the two-variant provisional/settled split, the
points estimate/actual split, the pinned evaluation order, supplies bulk pricing,
and the gold-bonus boundary.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula, boundary_precision_check.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_silver_member, create_member, create_open_visit, add_piece,
    fire_piece_to_ready, fire_pieces_to_ready, create_item,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ─── dual_variant_calc / visit_charge_provisional_vs_settled_silver ─────────

def test_provisional_excludes_silver_tier_discount(api):
    """PRD §3.2: "The provisional total is simply the sum of three running
    components: the studio_fee_cents, the bisque_subtotal_cents, and the
    supplies_subtotal_cents. Crucially, the provisional figure applies no discount
    and no loyalty redemption whatsoever."

    Design: Difficulty/dual_variant_calc/visit_charge_provisional_vs_settled_silver
    """
    member = create_silver_member()
    assert member["tier"] == "SILVER"
    visit = create_open_visit(member_id=member["id"])
    add_piece(visit["id"], bisque_price_cents=6000, sku="MUG-12OZ", name="Mug")
    add_piece(visit["id"], bisque_price_cents=4000, sku="BOWL-8IN", name="Bowl")

    read = validate_success(api.get_visit(visit["id"], STAFF), 200)
    # studio_fee 1000 + bisque 10000, no discount applied while OPEN
    assert read["provisional_total_cents"] == 11000, read["provisional_total_cents"]


def test_settled_applies_silver_tier_discount(api):
    """PRD §3.8: "the tier discount is the bisque subtotal multiplied by that
    percentage, rounded to the nearest whole cent with round-half-up." PRD §3.8:
    "The difference between the provisional estimate read while the visit was open
    and this settled figure is exactly the discount_cents."

    Design: Difficulty/dual_variant_calc/visit_charge_provisional_vs_settled_silver
    """
    member = create_silver_member()
    visit = create_open_visit(member_id=member["id"])
    # PRD §3.8 blocks checkout while any piece is still in the kiln pipeline, so the
    # pieces are fired to READY before settling.
    fire_pieces_to_ready(visit["id"], [6000, 4000])

    settled = validate_success(api.checkout_visit(visit["id"], {"points_redeemed": 0}, STAFF), 200)
    # 5% of 10000 bisque = 500 discount; 11000 - 500 = 10500
    assert settled["settled_total_cents"] == 10500, settled["settled_total_cents"]
    assert settled["discount_cents"] == 500, settled["discount_cents"]


# ─── dual_variant_calc / visit_points_estimate_vs_actual_silver ─────────────

def test_points_preview_uses_provisional_estimate(api):
    """PRD §3.8: "The points preview estimates points using the visit's gross
    provisional_total_cents as the net spend rather than the settled total, running
    the same one-point-per-100-cents floor and the same at-least-10000-cents bonus
    rule."

    Design: Difficulty/dual_variant_calc/visit_points_estimate_vs_actual_silver
    """
    member = create_silver_member()
    visit = create_open_visit(member_id=member["id"])
    # one piece 12000, fired to READY; provisional = 1000 fee + 12000 = 13000
    fire_piece_to_ready(visit["id"], bisque_price_cents=12000)

    preview = validate_success(api.get_visit_points_preview(visit["id"], STAFF), 200)
    # floor(13000/100)=130, >=10000 -> floor(130*1.5)=195
    assert preview["points_earned"] == 195, preview["points_earned"]


def test_points_actual_uses_settled_total(api):
    """PRD §3.8: "The points earned are computed from the post-discount net spend —
    the settled_total_cents itself." PRD §3.8: "the member's point_balance is
    increased by that amount."

    Design: Difficulty/dual_variant_calc/visit_points_estimate_vs_actual_silver
    """
    member = create_silver_member()  # lifetime 550, point_balance 550
    visit = create_open_visit(member_id=member["id"])
    fire_piece_to_ready(visit["id"], bisque_price_cents=12000)

    settled = validate_success(api.checkout_visit(visit["id"], {"points_redeemed": 0}, STAFF), 200)
    # settled = 13000 - round_half_up(12000*0.05=600) = 12400
    # floor(12400/100)=124, >=10000 -> floor(124*1.5)=186
    assert settled["points_earned"] == 186, settled["points_earned"]

    member_after = validate_success(api.get_member(member["id"], MANAGER), 200)
    assert member_after["point_balance"] == 736, member_after["point_balance"]  # 550 + 186


# ─── combinatorial_formula / settle_visit_pinned_eval_order_circular ────────

def test_settled_pinned_eval_order_silver_no_redeem(api):
    """PRD §3.8: "The settled charge is computed in a pinned order, because each
    step feeds the next. First the base components are summed... Their sum is the
    subtotal before discount. Second, the tier discount is computed, and it applies
    to the bisque subtotal only... Fourth, the settled_total_cents is the subtotal
    before discount minus the total discount, floored at 0."

    Design: Difficulty/combinatorial_formula/settle_visit_pinned_eval_order_circular
    """
    member = create_silver_member()
    visit = create_open_visit(member_id=member["id"])
    # PRD §3.8 blocks checkout while any piece is still in the kiln pipeline, so the
    # pieces are fired to READY before settling.
    fire_pieces_to_ready(visit["id"], [6000, 4000])

    settled = validate_success(api.checkout_visit(visit["id"], {"points_redeemed": 0}, STAFF), 200)
    assert settled["settled_total_cents"] == 10500, settled["settled_total_cents"]
    assert settled["discount_cents"] == 500, settled["discount_cents"]


def test_settled_base_components_pinned(api):
    """PRD §3.8: "First the base components are summed: the studio_fee_cents (the
    per-painter fee for a walk-in, 0 for a party), the bisque subtotal (the sum of
    bisque_price_cents over every piece on the visit that is not VOIDED)."
    PRD §3.2: "the studio_fee_cents is set to the number of painters multiplied by
    the per-painter studio fee of 1000 cents... for a WALK_IN."

    Design: Difficulty/combinatorial_formula/settle_visit_pinned_eval_order_circular
    """
    member = create_silver_member()
    visit = create_open_visit(member_id=member["id"])
    # PRD §3.8 blocks checkout while any piece is still in the kiln pipeline, so the
    # pieces are fired to READY before settling.
    fire_pieces_to_ready(visit["id"], [6000, 4000])

    settled = validate_success(api.checkout_visit(visit["id"], {"points_redeemed": 0}, STAFF), 200)
    assert settled["bisque_subtotal_cents"] == 10000, settled["bisque_subtotal_cents"]
    assert settled["studio_fee_cents"] == 1000, settled["studio_fee_cents"]


# ─── combinatorial_formula / supplies_charge_per_line_round_then_sum ────────

def test_supplies_bulk_round_per_line_then_sum(api):
    """PRD §3.7: "when the line quantity is at least 3, a bulk break applies,
    multiplying the line by nine-tenths (a ten-percent discount) and rounding that
    discounted line to the nearest whole cent with round-half-up. The rounding is
    applied per line, after the bulk multiplier, and the lines are then summed
    without any further rounding to produce the visit's supplies_subtotal_cents."

    Design: Difficulty/combinatorial_formula/supplies_charge_per_line_round_then_sum
    """
    item_a = create_item(unit_price_cents=500, on_hand=50, sku="GLZ-A", name="Glaze A")
    item_b = create_item(unit_price_cents=350, on_hand=50, sku="GLZ-B", name="Glaze B")
    visit = create_open_visit()

    api.consume_supply(visit["id"], {"paint_bar_item_id": item_a["id"], "qty": 3}, STAFF)
    after = validate_success(
        api.consume_supply(visit["id"], {"paint_bar_item_id": item_b["id"], "qty": 5}, STAFF), 201)
    # line A: round_half_up(3*500*0.9=1350)=1350 ; line B: round_half_up(5*350*0.9=1575)=1575
    assert after["supplies_subtotal_cents"] == 2925, after["supplies_subtotal_cents"]


def test_supplies_consume_decrements_on_hand(api):
    """PRD §3.7: "On a successful consume, the item's on_hand_qty is decreased by
    the consumed quantity and the visit's supplies_subtotal_cents and
    provisional_total_cents are recomputed."

    Design: Difficulty/combinatorial_formula/supplies_charge_per_line_round_then_sum
    """
    item_a = create_item(unit_price_cents=500, on_hand=50, sku="GLZ-A2", name="Glaze A2")
    item_b = create_item(unit_price_cents=350, on_hand=50, sku="GLZ-B2", name="Glaze B2")
    visit = create_open_visit()
    api.consume_supply(visit["id"], {"paint_bar_item_id": item_a["id"], "qty": 3}, STAFF)
    api.consume_supply(visit["id"], {"paint_bar_item_id": item_b["id"], "qty": 5}, STAFF)

    a_after = validate_success(api.get_paint_bar_item(item_a["id"], STAFF), 200)
    b_after = validate_success(api.get_paint_bar_item(item_b["id"], STAFF), 200)
    assert a_after["on_hand_qty"] == 47, a_after["on_hand_qty"]
    assert b_after["on_hand_qty"] == 45, b_after["on_hand_qty"]


# ─── boundary_precision_check / gold_bonus_threshold_at_10000_on_checkout ───

def test_gold_bonus_at_10000_settled_boundary(api):
    """PRD §3.8: "A bonus then applies when the net spend is at least 10000 cents:
    if the net spend meets or exceeds that threshold, the base points are multiplied
    by 1.5 and floored to a whole number; below the threshold, the points earned
    equal the base award with no multiplier. Exactly 10000 cents of net spend
    triggers the bonus; one cent less does not."

    Design: Difficulty/boundary_precision_check/gold_bonus_threshold_at_10000_on_checkout
    """
    member = create_member()  # BRONZE, no discount
    visit = create_open_visit(member_id=member["id"])
    # one piece 9000; provisional = 1000 fee + 9000 = 10000; BRONZE no discount
    fire_piece_to_ready(visit["id"], bisque_price_cents=9000)

    settled = validate_success(api.checkout_visit(visit["id"], {"points_redeemed": 0}, STAFF), 200)
    assert settled["settled_total_cents"] == 10000, settled["settled_total_cents"]
    # base floor(10000/100)=100, >=10000 -> floor(100*1.5)=150
    assert settled["points_earned"] == 150, settled["points_earned"]


def test_gold_bonus_below_10000_no_multiplier(api):
    """PRD §3.8: "below the threshold, the points earned equal the base award with
    no multiplier... one cent less does not [trigger the bonus]."

    Design: Difficulty/boundary_precision_check/gold_bonus_threshold_at_10000_on_checkout
    """
    member = create_member()  # BRONZE, no discount
    visit = create_open_visit(member_id=member["id"])
    # one piece 8999; provisional = 1000 + 8999 = 9999 < 10000
    fire_piece_to_ready(visit["id"], bisque_price_cents=8999)

    settled = validate_success(api.checkout_visit(visit["id"], {"points_redeemed": 0}, STAFF), 200)
    assert settled["settled_total_cents"] == 9999, settled["settled_total_cents"]
    # base floor(9999/100)=99, below threshold -> no bonus
    assert settled["points_earned"] == 99, settled["points_earned"]
