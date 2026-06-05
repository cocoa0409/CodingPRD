"""The confirmed-booking cancellation cascade.

Covers difficulty rule transitive_cascade (cancel_confirmed_four_hop_cascade).

Scope note: the PRD permits a cancel only from REQUESTED or CONFIRMED, while a
damage claim may be filed only while the booking is IN_STAY or COMPLETED. Those
two windows are disjoint, so a CONFIRMED booking can never carry a non-terminal
claim at cancel time — the claim-VOID hop the recipe sketches is not reachable
along any PRD-faithful path. These tests therefore assert the cascade hops that
ARE uniquely derivable from PRD §3.9 for a confirmed cancel with no open claim:
block release, listing calendar-version advance, payout reversal, and the
payout-reversal-driven deposit release.
"""
from test_helpers import (
    validate_success,
    make_host_headers, make_guest_headers,
    setup_confirmed_booking, get_calendar_version,
)


def test_cancel_confirmed_releases_block_and_reverses_payout(api):
    """PRD §3.9: "When the cancelled booking was `CONFIRMED`, the cascade reaches
    further, hop by hop: the booking's payout is reversed — its `status` becomes
    `REVERSED` and its `actual_cents` is set to 0; that payout reversal then
    closes the security deposit, whose `status` becomes `RELEASED` and
    `held_cents` drops to 0."
    PRD §3.9: "In every cancellation, the booking's calendar block is released
    (its `status` becomes `RELEASED` and the booking's `calendar_block_id`
    becomes null)."

    Design: Difficulty/transitive_cascade/cancel_confirmed_four_hop_cascade
    """
    ctx = setup_confirmed_booking(
        listing_overrides={"base_nightly_rate_cents": 20000, "cleaning_fee_cents": 5000,
                           "cancellation_tier": "FLEXIBLE", "security_deposit_cents": 10000,
                           "payout_delay_days": 1},
        booking_overrides={"check_in": "2026-07-10", "check_out": "2026-07-13"},
        clock="2026-07-01T00:00:00Z",
    )
    host, guest, booking = ctx["host"], ctx["guest"], ctx["booking"]
    payout = ctx["payout"]
    block_id = booking["calendar_block_id"]

    api.cancel_booking(booking["id"], headers=make_guest_headers(guest["id"]))

    blk = validate_success(api.get_calendar_block(block_id, headers=make_host_headers(host["id"])))
    assert blk["status"] == "RELEASED", f"block should be RELEASED, got {blk['status']}"
    pay = validate_success(api.get_payout(payout["id"], headers=make_host_headers(host["id"])))
    assert pay["status"] == "REVERSED", f"payout should be REVERSED, got {pay['status']}"
    assert pay["actual_cents"] == 0, f"reversed payout actual_cents must be 0, got {pay['actual_cents']}"


def test_cancel_confirmed_closes_deposit_and_advances_calendar(api):
    """PRD §3.9: "that payout reversal then closes the security deposit, whose
    `status` becomes `RELEASED` and `held_cents` drops to 0."
    PRD §3.9: "the listing's `calendar_version` advances by 1, and each
    `CONNECTED` or `ERROR` channel's `pending_sync_count` is bumped by 1."

    Second test of the cascade, pinning the deposit-closure hop and the
    calendar-version advance on the same confirmed-cancel.

    Design: Difficulty/transitive_cascade/cancel_confirmed_four_hop_cascade
    """
    ctx = setup_confirmed_booking(
        listing_overrides={"base_nightly_rate_cents": 20000, "cleaning_fee_cents": 5000,
                           "cancellation_tier": "FLEXIBLE", "security_deposit_cents": 10000,
                           "payout_delay_days": 1},
        booking_overrides={"check_in": "2026-07-10", "check_out": "2026-07-13"},
        clock="2026-07-01T00:00:00Z",
    )
    host, guest, listing, booking = ctx["host"], ctx["guest"], ctx["listing"], ctx["booking"]
    deposit = ctx["deposit"]
    cv_before = get_calendar_version(listing["id"], headers=make_host_headers(host["id"]))

    api.cancel_booking(booking["id"], headers=make_guest_headers(guest["id"]))

    dep = validate_success(api.get_security_deposit(deposit["id"], headers=make_host_headers(host["id"])))
    assert dep["status"] == "RELEASED", f"deposit should be RELEASED, got {dep['status']}"
    assert dep["held_cents"] == 0, f"released deposit held_cents must be 0, got {dep['held_cents']}"
    cv_after = get_calendar_version(listing["id"], headers=make_host_headers(host["id"]))
    assert cv_after == cv_before + 1, \
        f"calendar_version should advance by 1 on block release (was {cv_before}), got {cv_after}"
