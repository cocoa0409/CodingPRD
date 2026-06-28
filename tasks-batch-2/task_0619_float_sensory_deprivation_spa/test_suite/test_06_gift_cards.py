"""Gift-card balance reconciliation: depletion to exactly zero at check-in, and money
conservation across a deposit hold + timely refund."""
from test_helpers import (
    validate_success,
    setup_giftcard_reserved_booking_for_cancel,
    get_payments_for_booking,
    api_client, TEST_USERS,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]


# ─── Money conservation (ci_giftcard_money_conservation_hold_refund) ──────
def test_gift_card_balance_after_hold_is_reduced(api):
    """PRD §3.5: "Taking the deposit records a deposit-hold payment whose funding instrument
    mirrors the booking: a `GIFT_CARD` booking holds the deposit against the card (debiting
    it), while every other booking holds against `CASH`."

    Design: Difficulty/compensating_invariant/ci_giftcard_money_conservation_hold_refund
    """
    # initial 10000; single CASH deposit flat 2000 held against the card -> 8000.
    ctx = setup_giftcard_reserved_booking_for_cancel()
    gc = ctx["gift_card"]
    after_hold = validate_success(api.get_gift_card(gc["id"], FRONTDESK), 200)
    assert after_hold["remaining_balance_cents"] == 8000, (
        f"expected 8000 after hold, got {after_hold['remaining_balance_cents']}"
    )


def test_gift_card_balance_restored_after_timely_refund(api):
    """PRD §3.7: "When the booking was funded by a gift card, the `DEPOSIT_REFUND` carries a
    negative amount on the card and thereby restores the card's balance, so that a hold
    followed by a timely refund leaves the card exactly where it started."

    Design: Difficulty/compensating_invariant/ci_giftcard_money_conservation_hold_refund
    """
    ctx = setup_giftcard_reserved_booking_for_cancel()
    bk, gc = ctx["booking"], ctx["gift_card"]
    validate_success(api.cancel_booking(bk["id"], FRONTDESK), 200)
    after_refund = validate_success(api.get_gift_card(gc["id"], FRONTDESK), 200)
    assert after_refund["remaining_balance_cents"] == 10000, (
        f"expected balance restored to 10000, got {after_refund['remaining_balance_cents']}"
    )
    payments = get_payments_for_booking(bk["id"])
    holds = [p for p in payments if p["kind"] == "DEPOSIT_HOLD"
             and p["source"] == "GIFT_CARD" and p["amount_cents"] == 2000]
    refunds = [p for p in payments if p["kind"] == "DEPOSIT_REFUND"
               and p["source"] == "GIFT_CARD" and p["amount_cents"] == -2000]
    assert len(holds) == 1, f"expected one GIFT_CARD DEPOSIT_HOLD of 2000, got {holds}"
    assert len(refunds) == 1, f"expected one GIFT_CARD DEPOSIT_REFUND of -2000, got {refunds}"
