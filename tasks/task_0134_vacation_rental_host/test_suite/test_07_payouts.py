"""Payout scheduling, estimate-vs-actual divergence, the not-due temporal gate,
and the confirm-time satellite cascade visibility.

Covers difficulty rule dual_variant_calc (payout half) plus corner validations /
consistency_model payout instances.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_host_headers, make_guest_headers, admin_headers,
    setup_confirmed_booking, setup_in_stay_booking, set_clock, file_claim,
    get_booking_payout, get_booking_deposit,
)


# ==========================================================================
# Difficulty: dual_variant_calc (payout ESTIMATE vs ACTUAL)
# ==========================================================================
def test_payout_estimate_written_at_confirmation(api):
    """PRD §3.6: "The host gross is the booking's `nightly_subtotal_cents` plus
    its `fees_cents` — occupancy tax is remitted, not paid to the host, so it is
    excluded from the gross. The platform commission is that gross multiplied by
    the listing's `platform_commission_bps` divided by 10000, rounded once with
    round-half-up. The `estimated_cents` is the gross minus the commission; no
    deposit deductions are known yet at confirmation, so none are applied."

    Design: Difficulty/dual_variant_calc/payout_estimate_vs_actual_diverge_on_payout
    """
    ctx = setup_confirmed_booking(
        listing_overrides={"base_nightly_rate_cents": 20000, "cleaning_fee_cents": 5000,
                           "pet_fee_cents": 3000, "tax_rate_bps": 1000,
                           "cancellation_tier": "MODERATE", "security_deposit_cents": 10000,
                           "platform_commission_bps": 1500, "payout_delay_days": 1},
        rate_plan_overrides={"label": "PEAK", "window_start": "2026-07-01",
                             "window_end": "2026-07-31", "seasonal_multiplier_bps": 15000,
                             "weekend_multiplier_bps": 12000},
        booking_overrides={"check_in": "2026-07-10", "check_out": "2026-07-13", "pets_count": 1},
        clock="2026-07-01T16:00:00Z",
    )
    payout = ctx["payout"]
    # gross = 102000 + 8000 = 110000; commission = 16500; estimate = 93500.
    assert payout["estimated_cents"] == 93500, \
        f"estimated_cents should be 93500, got {payout['estimated_cents']}"
    assert payout["status"] == "SCHEDULED"


def test_payout_actual_at_release_subtracts_deductions(api):
    """PRD §3.8: "the actual payout is computed: the same host gross (booking
    `nightly_subtotal_cents` plus `fees_cents`) minus the same round-half-up
    commission (gross times `platform_commission_bps` divided by 10000), minus
    the total of the `approved_cents` of every `APPROVED` damage claim on the
    deposit, with the result floored at zero. This value is written to
    `actual_cents`; it may be smaller than the `estimated_cents` recorded at
    confirmation precisely because of those deposit deductions."

    Design: Difficulty/dual_variant_calc/payout_estimate_vs_actual_diverge_on_payout
    """
    ctx = setup_confirmed_booking(
        listing_overrides={"base_nightly_rate_cents": 20000, "cleaning_fee_cents": 5000,
                           "pet_fee_cents": 3000, "tax_rate_bps": 1000,
                           "cancellation_tier": "MODERATE", "security_deposit_cents": 10000,
                           "platform_commission_bps": 1500, "payout_delay_days": 1},
        rate_plan_overrides={"label": "PEAK", "window_start": "2026-07-01",
                             "window_end": "2026-07-31", "seasonal_multiplier_bps": 15000,
                             "weekend_multiplier_bps": 12000},
        booking_overrides={"check_in": "2026-07-10", "check_out": "2026-07-13", "pets_count": 1},
        clock="2026-07-01T16:00:00Z",
    )
    host, booking, deposit = ctx["host"], ctx["booking"], ctx["deposit"]
    # Drive to IN_STAY, file + approve a 4000 claim, complete, advance past release_after.
    set_clock("2026-07-10T12:00:00Z")
    claim = file_claim(host, deposit, 4000, reason="Broken lamp")
    api.review_claim(claim["id"], headers=admin_headers())
    api.approve_claim(claim["id"], headers=admin_headers())
    set_clock("2026-07-15T00:00:00Z")
    api.complete_booking(booking["id"], headers=make_host_headers(host["id"]))
    payout = get_booking_payout(host, booking)
    resp = api.release_payout(payout["id"], headers=admin_headers())
    after = validate_success(resp)
    # actual = 110000 - 16500 - 4000 = 89500.
    assert after["actual_cents"] == 89500, \
        f"actual_cents should be 89500 (110000-16500-4000), got {after['actual_cents']}"
    assert after["status"] == "RELEASED"


# ==========================================================================
# Corner: validations / payout temporal gate
# ==========================================================================
def test_payout_release_before_due_rejected(api):
    """PRD §3.8: "The clock must have reached the payout's `release_after`: a
    release attempted before the current instant reaches `release_after` is
    rejected with `ERR_PAYOUT_NOT_DUE` (HTTP 409)."

    Design: Corner/validations/payout_release_before_due_rejected
    """
    # payout_delay_days=5; checkout 2026-07-13 -> release_after 2026-07-18; clock 2026-07-13.
    ctx = setup_confirmed_booking(
        listing_overrides={"base_nightly_rate_cents": 20000, "cleaning_fee_cents": 5000,
                           "security_deposit_cents": 0, "payout_delay_days": 5},
        booking_overrides={"check_in": "2026-07-10", "check_out": "2026-07-13"},
        clock="2026-07-01T00:00:00Z",
    )
    host, booking = ctx["host"], ctx["booking"]
    set_clock("2026-07-13T00:00:00Z")
    api.complete_booking(booking["id"], headers=make_host_headers(host["id"]))
    payout = get_booking_payout(host, booking)
    resp = api.release_payout(payout["id"], headers=admin_headers())
    validate_error(resp, ApiErrorId.ERR_PAYOUT_NOT_DUE.value)


# ==========================================================================
# Corner: consistency_model / confirm cascade visible in same chain
# ==========================================================================
def test_confirm_creates_deposit_and_payout_immediately(api):
    """PRD §3.6: "First, a `SecurityDeposit` is created for the booking in
    `AUTHORIZED`, with its `authorized_cents` snapshotted from the listing's
    `security_deposit_cents` and its `held_cents` initialized to that same
    authorized amount. Second, a `Payout` is created for the booking in
    `SCHEDULED`, naming the `booking_id` and the recipient `host_id`; its
    `estimated_cents` is set from the estimate variant of the payout
    computation."

    Design: Corner/consistency_model/confirm_cascade_visible_same_response_chain
    """
    ctx = setup_confirmed_booking(
        listing_overrides={"base_nightly_rate_cents": 20000, "cleaning_fee_cents": 5000,
                           "tax_rate_bps": 0, "security_deposit_cents": 10000,
                           "platform_commission_bps": 1500, "payout_delay_days": 1},
        booking_overrides={"check_in": "2026-07-10", "check_out": "2026-07-13"},
        clock="2026-07-01T00:00:00Z",
    )
    host, booking = ctx["host"], ctx["booking"]
    deposit = get_booking_deposit(host, booking)
    assert deposit["status"] == "AUTHORIZED", f"deposit should be AUTHORIZED, got {deposit['status']}"
    assert deposit["authorized_cents"] == 10000, \
        f"authorized_cents snapshot should be 10000, got {deposit['authorized_cents']}"
    payout = get_booking_payout(host, booking)
    assert payout["status"] == "SCHEDULED", f"payout should be SCHEDULED, got {payout['status']}"
    # gross = 60000 + 5000 = 65000; commission = 9750; estimate = 55250.
    assert payout["estimated_cents"] == 55250, \
        f"estimated_cents should be 55250 (65000-9750), got {payout['estimated_cents']}"
