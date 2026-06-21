"""Charge-calculation corner cases: daily partial-day rounding, valet surcharge,
prepay-discount withholding, free-cancel full refund, overstay penalty, and pay-on-exit
capture.

Queue B (Corner) instances from the calculations section.
"""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    create_booked_reservation, create_checked_in_reservation, check_out_reservation_at,
    find_txn, set_clock, api_client, TEST_USERS,
)

ADMIN = TEST_USERS["facility_admin_headers"]
OPERATOR = TEST_USERS["lot_operator_headers"]


def _payment_txns(reservation_id):
    return get_success_data(api_client.list_reservation_payment_txns(reservation_id, ADMIN))


def test_daily_mode_partial_day_rounds_up_billable_days():
    """PRD §3.4: "Under `DAILY`, the billable days is the full days plus one more day
    if any remaining minutes exist, and the base is the billable days multiplied by
    `daily_cap_cents`."

    Design: Corner/calculations/daily_mode_partial_day_rounds_up_billable_days
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "Ld1", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-02T10:01:00Z")
    assert reservation["provisional_quote_cents"] == 4000


def test_valet_surcharge_only_on_valet_plan():
    """PRD §3.4: "Under `VALET`, the base is computed exactly as for `HOURLY` and then
    the flat `valet_surcharge_cents` is added once for the whole reservation."

    Design: Corner/calculations/valet_surcharge_only_on_valet_plan
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "Lvl", "kind": "VALET_GARAGE", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "VALET", "hourly_cents": 300, "daily_cap_cents": 2000,
                             "valet_surcharge_cents": 1500},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-02T10:00:00Z")
    assert reservation["provisional_quote_cents"] == 3500


def test_prepay_discount_withheld_when_lead_under_24h():
    """PRD §3.4: "The discount applies only when `prepaid` is true, **and** that lead
    time is at least 24 hours (that is, at least 24 times 60 minutes), **and** the
    booking customer's `no_show_strikes` is below three. ... A prepaid-but-too-late
    booking still authorizes the full, undiscounted gross."

    Design: Corner/calculations/prepay_discount_withheld_when_lead_under_24h
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-07-01T08:00:00Z",
        lot_overrides={"name": "Lpw", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        with_policy=True,
        policy_overrides={"free_cancel_hours": 48, "late_cancel_fee_bps": 0,
                          "prepay_discount_bps": 1500},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-02T10:00:00Z",
        prepaid=True)
    assert reservation["provisional_quote_cents"] == 2000
    assert reservation["settlement_status"] == "AUTHORIZED"


def test_free_cancel_full_refund_outside_window():
    """PRD §3.8: "If that gap is at least `free_cancel_hours`, the cancellation falls
    strictly outside (or exactly at the edge of) the free-cancel window and the retained
    fee is 0, so the full `provisional_quote_cents` is refunded."

    Design: Corner/calculations/free_cancel_full_refund_outside_window
    """
    scenario, reservation = create_booked_reservation(
        clock="2026-06-25T09:00:00Z",
        lot_overrides={"name": "Lfc", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        with_policy=True,
        policy_overrides={"free_cancel_hours": 48, "late_cancel_fee_bps": 2500,
                          "prepay_discount_bps": 0},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-02T10:00:00Z",
        prepaid=True)
    assert reservation["provisional_quote_cents"] == 2000

    cancelled = validate_success(api_client.cancel_reservation(reservation["id"], ADMIN), 200)
    assert cancelled["settlement_status"] == "REFUNDED"
    txns = _payment_txns(reservation["id"])
    refund = find_txn(txns, "REFUND")
    assert refund is not None and refund["amount_cents"] == 2000
    assert find_txn(txns, "FEE_RETAIN") is None


def test_overstay_beyond_grace_billed_at_penalty_rate():
    """PRD §3.6: "`overstay_cents` is the overstay hours multiplied by a per-hour
    penalty rate, where that penalty rate is the snapshot's `hourly_cents` multiplied by
    15000 divided by 10000 (that is, one and one-half times the hourly rate), rounded
    half up to a whole cent. The daily cap never limits overstay."

    Design: Corner/calculations/overstay_beyond_grace_billed_at_penalty_rate
    """
    scenario, checked_in = create_checked_in_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "Lob", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "HOURLY", "hourly_cents": 300, "daily_cap_cents": 2000},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-01T14:00:00Z",
        check_in_clock="2026-07-01T10:00:00Z")
    final = check_out_reservation_at(checked_in["id"], "2026-07-01T15:00:00Z")
    assert final["overstay_cents"] == 450
    assert final["final_charge_cents"] == 1950


def test_pay_on_exit_capture_full_final_charge():
    """PRD §3.6: "For a pay-on-exit reservation (settlement `UNSETTLED`), the system
    records a single `CAPTURE` for the full `final_charge_cents` (note 'pay-on-exit
    capture') and advances settlement from `UNSETTLED` directly to `SETTLED`."

    Design: Corner/calculations/pay_on_exit_capture_full_final_charge
    """
    scenario, checked_in = create_checked_in_reservation(
        clock="2026-06-30T09:00:00Z",
        lot_overrides={"name": "Lpe", "kind": "SURFACE_LOT", "standard_capacity": 5},
        rate_plan_overrides={"rate_mode": "DAILY", "daily_cap_cents": 2000},
        scheduled_start="2026-07-01T10:00:00Z", scheduled_end="2026-07-02T10:00:00Z",
        check_in_clock="2026-07-01T10:00:00Z", prepaid=False)
    final = check_out_reservation_at(checked_in["id"], "2026-07-02T09:00:00Z")
    assert final["settlement_status"] == "SETTLED"
    assert final["final_charge_cents"] == 2000

    txns = _payment_txns(checked_in["id"])
    captures = [t for t in txns if t["kind"] == "CAPTURE"]
    assert len(captures) == 1
    assert captures[0]["amount_cents"] == 2000
