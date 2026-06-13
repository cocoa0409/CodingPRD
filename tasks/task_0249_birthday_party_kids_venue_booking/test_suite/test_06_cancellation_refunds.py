"""Tiered cancellation refunds: the deposit-forfeit variant inside the 72-hour
window versus the full-refund variant at or beyond it.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    create_confirmed_booking, set_clock,
)

COORD = "coordinator_headers"
FIN = "finance_clerk_headers"


def _find_cancellation_refund(api, headers, booking_id):
    payments, _ = validate_paginated(api.list_payments(booking_id, headers))
    return [p for p in payments if p["direction"] == "REFUND"
            and p["purpose"] == "CANCELLATION_REFUND" and p["status"] == "SETTLED"]


# ─── Difficulty: dual_variant_calc / dvc_cancellation_refund_forfeit_vs_full ───

def test_cancel_inside_window_forfeits_deposit(api, coordinator_headers, finance_clerk_headers):
    """PRD 3.12: "Otherwise, if the hours to the event are at least 0 but less than 72
    (inside the forfeiture window but before the event), the deposit is forfeited: the
    refund is the amount paid minus `deposit_due_cents`, but never below zero."

    Design: Difficulty/dual_variant_calc/dvc_cancellation_refund_forfeit_vs_full
    """
    # CONFIRMED, paid full 46500 (CAKE + CHARACTER, children 8 -> deposit 11625).
    ctx = create_confirmed_booking(
        children_count=8, base_price_cents=30000, included_children=8,
        addons=[("CAKE", 4500), ("CHARACTER", 12000)], pay_amount=46500)
    bid = ctx["booking"]["id"]
    # 12 hours before the 2026-07-01T10:00 event: inside the 72h forfeiture window.
    set_clock("2026-06-30T22:00:00Z")

    cancelled = validate_success(api.cancel_booking(bid, coordinator_headers), 200)
    assert cancelled["status"] == "CANCELLED"
    # refund 34875; amount_paid back to the forfeited deposit 11625.
    assert cancelled["amount_paid_cents"] == 11625
    assert cancelled["payment_status"] == "DEPOSIT_PAID"

    refunds = _find_cancellation_refund(api, finance_clerk_headers, bid)
    assert len(refunds) == 1
    assert refunds[0]["amount_cents"] == 34875


def test_cancel_outside_window_full_refund(api, coordinator_headers, finance_clerk_headers):
    """PRD 3.12: "Otherwise, if the hours to the event are at least 72 — the
    free-cancellation window — the full paid amount is refunded."

    Design: Difficulty/dual_variant_calc/dvc_cancellation_refund_forfeit_vs_full
    """
    ctx = create_confirmed_booking(
        children_count=8, base_price_cents=30000, included_children=8,
        addons=[("CAKE", 4500), ("CHARACTER", 12000)], pay_amount=46500)
    bid = ctx["booking"]["id"]
    # Clock stays at 2026-06-25T09:00, which is well beyond 72h before 2026-07-01T10:00.
    cancelled = validate_success(api.cancel_booking(bid, coordinator_headers), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["amount_paid_cents"] == 0
    assert cancelled["payment_status"] == "REFUNDED"

    refunds = _find_cancellation_refund(api, finance_clerk_headers, bid)
    assert len(refunds) == 1
    assert refunds[0]["amount_cents"] == 46500
