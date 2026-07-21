"""Loyalty ledger and its cascades: the depth-3 class-cancel reversal chain, the special-order
fulfill award chain, the enroll/cancel points-conservation invariant, the SILVER tier
threshold, and the append-only ledger-row shape."""
import pytest
from test_helpers import (
    validate_success, validate_paginated,
    create_member, create_class, enroll, create_special_order,
    TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]


def _ledger_rows(api, member_id):
    data, _ = validate_paginated(api.list_member_loyalty_transactions(member_id, CLERK))
    return data


# =========================================================================
# Difficulty/transitive_cascade/class_cancel_cascades_to_loyalty_reversal
# =========================================================================
def test_class_cancel_cascades_to_enrollment_and_balance(api):
    """PRD §2.8: "Cancelling a class cancels each of its confirmed enrollments, and each
    enrollment cancellation in turn reverses that member's loyalty and recomputes the member's
    balance and tier." A member enrolled at fee 60.00 holds 600 points; cancelling the class
    cancels the enrollment and reverses the member's balance to 0.

    Design: Difficulty/transitive_cascade/class_cancel_cascades_to_loyalty_reversal
    """
    member = create_member(api)
    cls = create_class(api, capacity=10, fee=60.00, title="Retreat", event_type="RETREAT",
                       start_time="2026-10-01T09:00:00Z", end_time="2026-10-03T17:00:00Z")
    enrollment = enroll(api, cls["id"], member["id"])
    class_after = validate_success(api.cancel_class(cls["id"], CLERK), 200)
    assert class_after["status"] == "CANCELLED"
    enr_after = validate_success(api.get_enrollment(enrollment["id"], CLERK), 200)
    assert enr_after["status"] == "CANCELLED"
    member_after = validate_success(api.get_member(member["id"], CLERK), 200)
    assert member_after["points_balance"] == 0, f"expected 0, got {member_after['points_balance']}"


def test_class_cancel_writes_reversal_ledger_row(api):
    """PRD §3.5: "Cancellation moves the enrollment to the terminal CANCELLED state and
    reverses its loyalty: a LoyaltyTransaction with reason ENROLLMENT_CANCEL_REVERSAL is
    appended for the negative of the enrollment's original points_earned". A fee-60.00
    enrollment earns 600 points, so the reversal row created by the class cancellation carries
    -600.

    Design: Difficulty/transitive_cascade/class_cancel_cascades_to_loyalty_reversal
    """
    member = create_member(api)
    cls = create_class(api, capacity=10, fee=60.00, title="Retreat", event_type="RETREAT",
                       start_time="2026-10-01T09:00:00Z", end_time="2026-10-03T17:00:00Z")
    enroll(api, cls["id"], member["id"])
    validate_success(api.cancel_class(cls["id"], CLERK), 200)
    rows = _ledger_rows(api, member["id"])
    reversals = [r for r in rows if r["reason"] == "ENROLLMENT_CANCEL_REVERSAL"]
    assert len(reversals) == 1, f"expected one reversal row, got {len(reversals)}"
    assert reversals[0]["points"] == -600, f"expected -600, got {reversals[0]['points']}"


# =========================================================================
# Difficulty/transitive_cascade/special_order_fulfill_earns_loyalty
# =========================================================================
def test_special_order_fulfill_recomputes_member_balance(api):
    """PRD §3.6: "Fulfillment also awards loyalty: a LoyaltyTransaction with reason
    SPECIAL_ORDER_FULFILL is appended for the member, with a points award equal to the final
    total times ten points per dollar, floored to a whole number, after which the member's
    points_balance and loyalty_tier are recomputed." final_total = 12.00*3*1.5 + 5.00 = 59.00,
    so the award is floor(59*10) = 590 and the member's balance becomes 590.

    Design: Difficulty/transitive_cascade/special_order_fulfill_earns_loyalty
    """
    order, member_id = create_special_order(api, quantity=3, est_unit_cost=10.00,
                                             description="Thread cones")
    data = validate_success(
        api.fulfill_special_order(order["id"], {"actual_unit_cost": 12.00, "shipping_cost": 5.00}, CLERK),
        200)
    assert data["status"] == "FULFILLED"
    member_after = validate_success(api.get_member(member_id, CLERK), 200)
    assert member_after["points_balance"] == 590, f"expected 590, got {member_after['points_balance']}"


def test_special_order_fulfill_appends_award_ledger_row(api):
    """PRD §3.6: "a LoyaltyTransaction with reason SPECIAL_ORDER_FULFILL is appended for the
    member, with a points award equal to the final total times ten points per dollar, floored
    to a whole number". With final_total 59.00 the appended award row carries 590 points.

    Design: Difficulty/transitive_cascade/special_order_fulfill_earns_loyalty
    """
    order, member_id = create_special_order(api, quantity=3, est_unit_cost=10.00,
                                             description="Thread cones")
    validate_success(
        api.fulfill_special_order(order["id"], {"actual_unit_cost": 12.00, "shipping_cost": 5.00}, CLERK),
        200)
    rows = _ledger_rows(api, member_id)
    awards = [r for r in rows if r["reason"] == "SPECIAL_ORDER_FULFILL"]
    assert len(awards) == 1, f"expected one award row, got {len(awards)}"
    assert awards[0]["points"] == 590, f"expected 590, got {awards[0]['points']}"


# =========================================================================
# Difficulty/compensating_invariant/loyalty_points_conserved_on_enroll_cancel
# =========================================================================
def test_enroll_then_cancel_restores_balance(api):
    """PRD §3.5: "its points_earned is the class fee times ten points per dollar, floored to a
    whole number". PRD §3.5: "Cancellation ... reverses its loyalty: a LoyaltyTransaction with
    reason ENROLLMENT_CANCEL_REVERSAL is appended for the negative of the enrollment's
    original points_earned, and the member's balance and tier are recomputed." A fee-30.00
    enrollment earns +300; cancelling it writes -300 and returns the balance to 0.

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_on_enroll_cancel
    """
    member = create_member(api)
    cls = create_class(api, capacity=5, fee=30.00, title="Comp",
                       start_time="2026-11-01T10:00:00Z", end_time="2026-11-01T12:00:00Z")
    enrollment = enroll(api, cls["id"], member["id"])
    enr_after = validate_success(api.cancel_enrollment(enrollment["id"], CLERK), 200)
    assert enr_after["status"] == "CANCELLED"
    member_after = validate_success(api.get_member(member["id"], CLERK), 200)
    assert member_after["points_balance"] == 0, f"expected 0, got {member_after['points_balance']}"


def test_enroll_cancel_ledger_nets_to_zero(api):
    """PRD §2.9: "A member's points_balance is always the signed sum of every one of that
    member's ledger rows, with no filtering by reason or sign — reversals net directly against
    awards." A fee-30.00 enrollment appends +300, and its cancellation appends a -300 reversal
    (reason ENROLLMENT_CANCEL_REVERSAL), so the two ledger rows net to a balance of 0.

    Design: Difficulty/compensating_invariant/loyalty_points_conserved_on_enroll_cancel
    """
    member = create_member(api)
    cls = create_class(api, capacity=5, fee=30.00, title="Comp",
                       start_time="2026-11-01T10:00:00Z", end_time="2026-11-01T12:00:00Z")
    enrollment = enroll(api, cls["id"], member["id"])
    validate_success(api.cancel_enrollment(enrollment["id"], CLERK), 200)
    rows = _ledger_rows(api, member["id"])
    assert sum(r["points"] for r in rows) == 0, "ledger rows must net to zero"
    reversals = [r for r in rows if r["reason"] == "ENROLLMENT_CANCEL_REVERSAL"]
    assert len(reversals) == 1 and reversals[0]["points"] == -300


# =========================================================================
# Corner/entities/loyalty_tier_silver_at_threshold
# =========================================================================
def test_loyalty_tier_silver_exactly_at_threshold(api):
    """PRD §2.9: "SILVER once the balance reaches 1,000 but remains below 5,000". A single
    enrollment at fee 100.00 earns floor(100*10) = 1000 points, landing the balance exactly at
    the SILVER threshold, so loyalty_tier becomes SILVER.

    Design: Corner/entities/loyalty_tier_silver_at_threshold
    """
    member = create_member(api)
    cls = create_class(api, capacity=8, fee=100.00, title="Masterclass",
                       start_time="2026-09-25T10:00:00Z", end_time="2026-09-25T16:00:00Z")
    enroll(api, cls["id"], member["id"])
    data = validate_success(api.get_member(member["id"], CLERK), 200)
    assert data["points_balance"] == 1000, f"expected 1000, got {data['points_balance']}"
    assert data["loyalty_tier"] == "SILVER", f"expected SILVER, got {data['loyalty_tier']}"


# =========================================================================
# Corner/entities/loyalty_transaction_ledger_row_immutable_shape
# =========================================================================
def test_loyalty_ledger_row_is_append_only_shape(api):
    """PRD §2.9: "a LoyaltyTransaction with reason ENROLLMENT_CONFIRM is appended for that
    amount". PRD §2.4: "A LoyaltyTransaction is an append-only ledger row: it carries only id
    and created_at, and has neither updated_at nor version." A fee-30.00 enrollment surfaces
    one ledger row of 300 points with reason ENROLLMENT_CONFIRM and no version field.

    Design: Corner/entities/loyalty_transaction_ledger_row_immutable_shape
    """
    member = create_member(api)
    cls = create_class(api, capacity=8, fee=30.00, title="Basics",
                       start_time="2026-09-26T10:00:00Z", end_time="2026-09-26T12:00:00Z")
    enroll(api, cls["id"], member["id"])
    rows = _ledger_rows(api, member["id"])
    assert len(rows) == 1, f"expected one ledger row, got {len(rows)}"
    row = rows[0]
    assert row["points"] == 300, f"expected 300, got {row['points']}"
    assert row["reason"] == "ENROLLMENT_CONFIRM"
    assert "version" not in row, "ledger row must not carry a version"
    assert "updated_at" not in row, "ledger row must not carry an updated_at"
