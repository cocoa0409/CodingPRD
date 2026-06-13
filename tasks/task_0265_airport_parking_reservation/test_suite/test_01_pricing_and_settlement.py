"""Pricing engine: provisional vs final charge, combinatorial tiers, prepay discount,
overstay penalty boundary, and money conservation on settlement.

Queue A (Difficulty) instances for dual_variant_calc, combinatorial_formula, the
overstay boundary slice of boundary_precision_check, and the money slice of
compensating_invariant.
"""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    create_booked_reservation, create_checked_in_reservation, check_out_reservation_at,
    setup_booking_scenario, book_reservation, set_clock, list_payment_txns, find_txn,
    api_client, TEST_USERS,
)

ADMIN = TEST_USERS["facility_admin_headers"]


def _payment_txns(reservation_id):
    res = api_client.list_reservation_payment_txns(reservation_id, ADMIN)
    return get_success_data(res)


# ─── Rule 1: dual_variant_calc ───────────────────────────────────────────────
def test_provisional_and_final_charge_diverge_with_overstay():
    """PRD §3.4: "At booking time the **provisional variant** runs over the interval
    from `scheduled_start` to `scheduled_end`, and the gross it produces is the
    pre-discount basis for `provisional_quote_cents`; overstay is never considered
    here, since a planned interval cannot overstay itself."
    PRD §3.6: "Check-out then runs the **final variant** of the charge calculation
    over the interval from `actual_in` to `actual_out`, producing the gross charge by
    the same pinned steps as the provisional variant, and adds any overstay surcharge
    to produce `final_charge_cents`."

    Design: Difficulty/dual_variant_calc/parking_charge_provisional_vs_final_diverge
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L1", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "HOURLY", "hourly_cents": 300, "daily_cap_cents": 2000},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-03T15:30:00Z",
        prepaid=False)
    assert reservation["provisional_quote_cents"] == 5800

    set_clock("2026-07-01T10:00:00Z")
    validate_success(api_client.check_in_reservation(reservation["id"],
                     TEST_USERS["lot_operator_headers"]), 200)
    final = check_out_reservation_at(reservation["id"], "2026-07-03T18:00:00Z")
    assert final["final_charge_cents"] == 6900
    assert final["overstay_cents"] == 900
    assert final["provisional_quote_cents"] != final["final_charge_cents"]


def test_lot_availability_decrements_on_hold_then_increments_on_release():
    """PRD §2.5: "the available count for that class equals that class's capacity minus
    the number of stall holds on the lot whose own stall class matches and whose
    `status` is either `HELD` or `OCCUPIED`."
    PRD §3.8: "the backing stall hold goes from `HELD` to `RELEASED`, the lot's
    availability counter for that class is recomputed upward by one".

    Design: Difficulty/dual_variant_calc/lot_availability_decrement_vs_increment_diverge
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L2", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-02T10:00:00Z")
    after_hold = get_success_data(api_client.get_lot(scenario["lot"]["id"], ADMIN))
    assert after_hold["available_standard_count"] == 4

    validate_success(api_client.cancel_reservation(reservation["id"], ADMIN), 200)
    after_release = get_success_data(api_client.get_lot(scenario["lot"]["id"], ADMIN))
    assert after_release["available_standard_count"] == 5


# ─── Rule 2: combinatorial_formula ───────────────────────────────────────────
# NOTE: the difficulty instance `hourly_charge_tiered_cap_with_class_surcharge_mode_a`
# is SKIPPED. Its setup interval (2026-07-01T10:00 → 2026-07-02T12:00 = 1 day + 2 h)
# produces, under the PRD's pinned charge algorithm (§3.4), an OVERSIZED provisional of
# 3720 ( base = 1*min(24*300, 2500) + min(ceil(120/60)*300, 2500) = 2500 + 600 = 3100,
# then *12000/10000 = 3720 ), NOT the asserted 6000. The asserted value is therefore not
# uniquely derivable from the PRD prose for the literal setup, so no test is emitted.
def test_prepay_discount_on_quote_overstay_capture_undiscounted():
    """PRD §3.4: "the discount is the gross multiplied by the lot's cancellation-policy
    `prepay_discount_bps` divided by 10000, rounded half up to a whole cent, and
    `provisional_quote_cents` is the gross minus that discount."
    PRD §3.6: "If `final_charge_cents` exceeds `provisional_quote_cents`, an additional
    `CAPTURE` transaction is recorded for the difference (`final_charge_cents` minus
    `provisional_quote_cents`, note 'overstay capture') — the prepay discount does not
    apply to this overstay delta."

    Design: Difficulty/combinatorial_formula/prepay_discount_then_overstay_capture_evaluation_order_mode_c
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L2c", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "HOURLY", "hourly_cents": 300, "daily_cap_cents": 2000},
        with_policy=True,
        policy_overrides={"free_cancel_hours": 48, "late_cancel_fee_bps": 2500,
                          "prepay_discount_bps": 1500},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-03T15:30:00Z",
        prepaid=True)
    assert reservation["provisional_quote_cents"] == 4930

    set_clock("2026-07-01T10:00:00Z")
    validate_success(api_client.check_in_reservation(reservation["id"],
                     TEST_USERS["lot_operator_headers"]), 200)
    final = check_out_reservation_at(reservation["id"], "2026-07-03T18:00:00Z")
    assert final["final_charge_cents"] == 6900

    txns = _payment_txns(reservation["id"])
    captures = [t for t in txns if t["kind"] == "CAPTURE"]
    capture_amounts = sorted(t["amount_cents"] for t in captures)
    assert 4930 in capture_amounts, f"expected prepay capture 4930 in {capture_amounts}"
    assert 1970 in capture_amounts, f"expected overstay capture 1970 in {capture_amounts}"


# ─── Rule 6 (boundary slice): overstay grace boundary ────────────────────────
def test_overstay_zero_at_exactly_59_minutes_past_end():
    """PRD §3.6: "A grace window extends 59 minutes past the planned departure: the
    grace end is `scheduled_end` plus 59 minutes. If `actual_out` is at or before that
    grace end, `overstay_cents` is 0 and `final_charge_cents` equals the gross."

    Design: Difficulty/boundary_precision_check/overstay_grace_boundary_at_59_vs_60_min
    """
    scenario, checked_in = create_checked_in_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L6a", "kind": "SURFACE_LOT", "standard_capacity": 2},
        rate_plan_overrides={"rate_mode": "HOURLY", "hourly_cents": 300, "daily_cap_cents": 2000},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-01T14:00:00Z",
        check_in_clock="2026-07-01T10:00:00Z")
    final = check_out_reservation_at(checked_in["id"], "2026-07-01T14:59:00Z")
    assert final["overstay_cents"] == 0


def test_overstay_billed_at_penalty_rate_one_minute_past_grace():
    """PRD §3.6: "Otherwise the overstay minutes is the time from the grace end to
    `actual_out`, rounded **up** to a whole minute; the overstay hours is those minutes
    divided by 60, rounded **up** to a whole hour; and `overstay_cents` is the overstay
    hours multiplied by a per-hour penalty rate, where that penalty rate is the
    snapshot's `hourly_cents` multiplied by 15000 divided by 10000 (that is, one and
    one-half times the hourly rate), rounded half up to a whole cent."

    Design: Difficulty/boundary_precision_check/overstay_grace_boundary_at_59_vs_60_min
    """
    scenario, checked_in = create_checked_in_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L6a2", "kind": "SURFACE_LOT", "standard_capacity": 2},
        rate_plan_overrides={"rate_mode": "HOURLY", "hourly_cents": 300, "daily_cap_cents": 2000},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-01T14:00:00Z",
        check_in_clock="2026-07-01T10:00:00Z")
    final = check_out_reservation_at(checked_in["id"], "2026-07-01T15:00:00Z")
    assert final["overstay_cents"] == 450
    assert final["final_charge_cents"] == 1950


# ─── Rule 9 (money slice): compensating_invariant ────────────────────────────
def test_money_conserved_prepay_then_late_cancel_fee_plus_refund():
    """PRD §3.8: "the retained fee is `provisional_quote_cents` multiplied by the
    policy's `late_cancel_fee_bps` divided by 10000, rounded half up to a whole cent.
    The refund is the exact complement: `provisional_quote_cents` minus the retained
    fee, so the two always sum to `provisional_quote_cents`."
    PRD §3.8: "When a fee is retained the system records a `FEE_RETAIN` payment
    transaction for the fee and a `REFUND` transaction for the refunded remainder and
    advances settlement from `AUTHORIZED` to `REFUNDED`".

    Design: Difficulty/compensating_invariant/money_conserved_prepay_then_cancel_fee_plus_refund
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "L9b", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "HOURLY", "hourly_cents": 300, "daily_cap_cents": 2000},
        with_policy=True,
        policy_overrides={"free_cancel_hours": 48, "late_cancel_fee_bps": 2500,
                          "prepay_discount_bps": 1500},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-03T15:30:00Z",
        prepaid=True)
    assert reservation["provisional_quote_cents"] == 4930

    set_clock("2026-06-30T20:00:00Z")
    cancelled = validate_success(api_client.cancel_reservation(reservation["id"], ADMIN), 200)
    assert cancelled["settlement_status"] == "REFUNDED"

    txns = _payment_txns(reservation["id"])
    fee = find_txn(txns, "FEE_RETAIN")
    refund = find_txn(txns, "REFUND")
    assert fee is not None and refund is not None
    assert fee["amount_cents"] == 1233
    assert refund["amount_cents"] == 3697
    assert fee["amount_cents"] + refund["amount_cents"] == 4930
