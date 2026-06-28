"""Calculation corners: party deposit, long-series bonus, anonymous zero points,
floor-at-zero settlement, SILVER tier boundary, sub-threshold supplies.

Queue B (Corner): section calculations.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_member, create_open_visit, add_piece, create_series, create_item,
    create_member_with_lifetime, fire_piece_to_ready,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]
MANAGER = TEST_USERS["manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_party_deposit_deluxe(api):
    """PRD §3.6: "The per-head rate is 4500 cents for a BASIC package and 8000 cents
    for a DELUXE package. The package_total_cents is the guest_count multiplied by
    that per-head rate. The deposit_due_cents is one quarter of the package total —
    the package total multiplied by 0.25 — rounded to the nearest whole cent using
    round-half-up."

    Design: Corner/calculations/party_deposit_deluxe_correct
    """
    member = create_member()
    res = api.create_booking(
        {"member_id": member["id"], "package_tier": "DELUXE", "guest_count": 10,
         "scheduled_for": "2026-09-10T18:00:00Z"}, STAFF)
    booking = validate_success(res, 201)
    assert booking["package_total_cents"] == 80000, booking["package_total_cents"]
    assert booking["deposit_due_cents"] == 20000, booking["deposit_due_cents"]


def test_enrollment_long_series_bonus(api):
    """PRD §3.10: "A long-series bonus then adds a flat 50 points when the series
    runs at least 6 sessions — that is, when the session_count is 6 or more, the
    points earned are the base award plus 50."

    Design: Corner/calculations/enrollment_long_series_bonus
    """
    member = create_member()
    series = create_series(session_count=6, seat_capacity=5, price_cents=18000,
                           starts_at="2026-07-01T18:00:00Z")
    enr = validate_success(api.enroll(series["id"], {"member_id": member["id"]}, STAFF), 201)
    # floor(18000/100)=180 base + 50 long-series bonus
    assert enr["points_earned"] == 230, enr["points_earned"]
    member_after = validate_success(api.get_member(member["id"], MANAGER), 200)
    assert member_after["point_balance"] == 230, member_after["point_balance"]


def test_anonymous_visit_earns_zero_points(api):
    """PRD §3.8: "An anonymous visit earns 0 points, and points_earned is 0 while a
    visit is OPEN regardless."

    Design: Corner/calculations/anonymous_visit_earns_zero_points
    """
    visit = create_open_visit()  # anonymous, member_id omitted
    # one piece 4000, fired & ready; settled = 1000 fee + 4000 = 5000
    fire_piece_to_ready(visit["id"], bisque_price_cents=4000)
    settled = validate_success(api.checkout_visit(visit["id"], {"points_redeemed": 0}, STAFF), 200)
    assert settled["settled_total_cents"] == 5000, settled["settled_total_cents"]
    assert settled["points_earned"] == 0, settled["points_earned"]


def test_checkout_total_floored_at_zero(api):
    """PRD §3.8: "the settled_total_cents is the subtotal before discount minus the
    total discount, floored at 0 so it can never go negative." PRD §3.8: "the
    points_earned is pinned on the visit, the member's point_balance is increased by
    that amount."

    Design: Corner/calculations/checkout_total_floored_at_zero
    """
    # member earns 5000 points via a 500000/4 enrollment (floor(500000/100)=5000)
    member, _series, _enr = create_member_with_lifetime(price_cents=500000, session_count=4)
    assert member["point_balance"] == 5000, member["point_balance"]
    visit = create_open_visit(member_id=member["id"])
    # one piece 1000, fired; subtotal before discount = 1000 fee + 1000 bisque = 2000
    fire_piece_to_ready(visit["id"], bisque_price_cents=1000)
    settled = validate_success(api.checkout_visit(visit["id"], {"points_redeemed": 5000}, STAFF), 200)
    # redemption 5000 alone exceeds the 2000 subtotal -> floor to 0
    assert settled["settled_total_cents"] == 0, settled["settled_total_cents"]
    member_after = validate_success(api.get_member(member["id"], MANAGER), 200)
    # 5000 redeemed; 0 earned on a 0 settled total
    assert member_after["point_balance"] == 0, member_after["point_balance"]


def test_member_tier_silver_at_500_boundary(api):
    """PRD §3.1: "a member with at least 500 points is SILVER... Exactly 500 lifetime
    points lands on SILVER." PRD §3.10: base award is "amount_paid_cents divided by
    100 and floored"; the long-series bonus only applies "when the session_count is
    6 or more."

    Design: Corner/calculations/member_tier_silver_at_500_boundary
    """
    member = create_member()
    series = create_series(session_count=4, seat_capacity=5, price_cents=50000,
                           starts_at="2026-07-01T18:00:00Z")
    api.enroll(series["id"], {"member_id": member["id"]}, STAFF)
    member_after = validate_success(api.get_member(member["id"], MANAGER), 200)
    # floor(50000/100)=500, session_count 4 -> no bonus
    assert member_after["lifetime_points_earned"] == 500, member_after["lifetime_points_earned"]
    assert member_after["tier"] == "SILVER", member_after["tier"]


def test_supplies_no_bulk_below_threshold(api):
    """PRD §3.7: "The charge for the line is the quantity multiplied by the item's
    unit_price_cents, with one twist: when the line quantity is at least 3, a bulk
    break applies." PRD §3.7: "the item's on_hand_qty is decreased by the consumed
    quantity."

    Design: Corner/calculations/supplies_no_bulk_below_threshold
    """
    item = create_item(unit_price_cents=500, on_hand=50, sku="GLZ-D", name="Glaze D")
    visit = create_open_visit()
    after = validate_success(
        api.consume_supply(visit["id"], {"paint_bar_item_id": item["id"], "qty": 2}, STAFF), 201)
    # qty 2 < 3 -> no bulk break: 2*500 = 1000
    assert after["supplies_subtotal_cents"] == 1000, after["supplies_subtotal_cents"]
    item_after = validate_success(api.get_paint_bar_item(item["id"], STAFF), 200)
    assert item_after["on_hand_qty"] == 48, item_after["on_hand_qty"]
