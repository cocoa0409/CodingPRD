"""Cancellation refund: provisional-vs-final divergence, lead-hour tier
boundaries, and the occupied-nights conservation invariant.

Covers difficulty rules dual_variant_calc (refund half), boundary_precision_check
(lead-hour half), and compensating_invariant (occupied-nights half).
"""
from test_helpers import (
    validate_success, validate_paginated,
    make_host_headers, make_guest_headers,
    create_host, create_guest, create_listed_listing,
    setup_confirmed_booking, set_clock, get_calendar_version,
)


# ==========================================================================
# Difficulty: dual_variant_calc (PROVISIONAL quote vs FINAL refund diverge)
# ==========================================================================
def test_cancellation_quote_provisional_full_band(api):
    """PRD §3.9: "Under `MODERATE`, a lead time of at least 120 hours refunds 100
    percent, a lead time of at least 24 hours (but under 120) refunds 50 percent,
    and anything less refunds 0 percent."
    PRD §3.9: "The quote returns the `refund_cents` the guest would receive if
    they cancelled right now, the `applied_pct` (the refund percentage that would
    apply), and the `lead_hours` measured from the current instant; it writes
    nothing."

    Design: Difficulty/dual_variant_calc/cancellation_refund_provisional_vs_final_diverge_on_booking
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
    host, guest, booking = ctx["host"], ctx["guest"], ctx["booking"]
    # refundable_base = nightly_subtotal 102000 + tax 11000 = 113000; lead 200h -> 100%.
    resp = api.cancellation_quote(booking["id"], headers=make_guest_headers(guest["id"]))
    data = validate_success(resp)
    assert data["refund_cents"] == 113000, \
        f"Provisional quote at 200h MODERATE should be 113000 (100%), got {data['refund_cents']}"
    assert data["applied_pct"] == 100, f"applied_pct should be 100, got {data['applied_pct']}"


def test_cancellation_final_refund_diverges_from_provisional(api):
    """PRD §3.9: "Because the lead time is measured at the moment of the call, a
    provisional quote taken earlier and a final settlement at the actual cancel
    instant may land in different tier bands and therefore differ for identical
    booking data — the committed `refund_cents` always reflects the lead time at
    the cancel instant."
    PRD §3.9: "Under `MODERATE`, a lead time of at least 120 hours refunds 100
    percent, a lead time of at least 24 hours (but under 120) refunds 50 percent,
    and anything less refunds 0 percent."

    Design: Difficulty/dual_variant_calc/cancellation_refund_provisional_vs_final_diverge_on_booking
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
    guest, booking = ctx["guest"], ctx["booking"]
    # Advance to 2026-07-05T20:00:00Z -> lead ~100h -> MODERATE 50% band; 113000*50% = 56500.
    set_clock("2026-07-05T20:00:00Z")
    resp = api.cancel_booking(booking["id"], headers=make_guest_headers(guest["id"]))
    after = validate_success(resp)
    assert after["refund_cents"] == 56500, \
        f"FINAL refund at 100h MODERATE should be 56500 (50%), got {after['refund_cents']}"
    assert after["status"] == "CANCELLED"


# ==========================================================================
# Difficulty: boundary_precision_check (lead-hour tier boundary)
# ==========================================================================
def test_flexible_refund_full_above_lead_boundary(api):
    """PRD §3.9: "Under `FLEXIBLE`, a lead time of at least 24 hours refunds 100
    percent and anything less refunds 0 percent."
    PRD §3.9: "The quote returns the `refund_cents` the guest would receive if
    they cancelled right now, the `applied_pct` (the refund percentage that would
    apply), and the `lead_hours` measured from the current instant; it writes
    nothing."

    Design: Difficulty/boundary_precision_check/cancellation_lead_hour_tier_boundary_on_cancel
    """
    ctx = setup_confirmed_booking(
        listing_overrides={"base_nightly_rate_cents": 10000, "cleaning_fee_cents": 0,
                           "tax_rate_bps": 0, "cancellation_tier": "FLEXIBLE",
                           "security_deposit_cents": 0},
        booking_overrides={"check_in": "2026-07-10", "check_out": "2026-07-13"},
        clock="2026-07-01T00:00:00Z",
    )
    guest, booking = ctx["guest"], ctx["booking"]
    # refundable_base = 30000 + 0 tax; lead 216h >= 24 -> 100%.
    resp = api.cancellation_quote(booking["id"], headers=make_guest_headers(guest["id"]))
    data = validate_success(resp)
    assert data["refund_cents"] == 30000, \
        f"FLEXIBLE 216h >= 24 should refund 100% = 30000, got {data['refund_cents']}"


def test_flexible_refund_zero_below_lead_boundary(api):
    """PRD §3.9: "Under `FLEXIBLE`, a lead time of at least 24 hours refunds 100
    percent and anything less refunds 0 percent."
    PRD §3.9: "The lead time is the number of whole hours between the current
    instant and the booking's `check_in`, taken as zero or greater — if check-in
    has already passed, the lead time is treated as zero."

    Boundary precision: lead_hours = 23 (< 24) refunds 0%.

    Design: Difficulty/boundary_precision_check/cancellation_lead_hour_tier_boundary_on_cancel
    """
    ctx = setup_confirmed_booking(
        listing_overrides={"base_nightly_rate_cents": 10000, "cleaning_fee_cents": 0,
                           "tax_rate_bps": 0, "cancellation_tier": "FLEXIBLE",
                           "security_deposit_cents": 0},
        booking_overrides={"check_in": "2026-07-10", "check_out": "2026-07-13"},
        clock="2026-07-01T00:00:00Z",
    )
    guest, booking = ctx["guest"], ctx["booking"]
    # 2026-07-09T01:00:00Z -> 23h before 07-10T00:00 check_in -> < 24 -> 0%.
    set_clock("2026-07-09T01:00:00Z")
    resp = api.cancel_booking(booking["id"], headers=make_guest_headers(guest["id"]))
    after = validate_success(resp)
    assert after["refund_cents"] == 0, \
        f"FLEXIBLE 23h < 24 should refund 0, got {after['refund_cents']}"


# ==========================================================================
# Difficulty: compensating_invariant (occupied-nights conservation)
# ==========================================================================
def test_cancel_conserves_active_block_count(api):
    """PRD §3.9: "In every cancellation, the booking's calendar block is released
    (its `status` becomes `RELEASED` and the booking's `calendar_block_id`
    becomes null), the listing's `calendar_version` advances by 1, and each
    `CONNECTED` or `ERROR` channel's `pending_sync_count` is bumped by 1."

    Design: Difficulty/compensating_invariant/cancel_conserves_listing_occupied_nights
    """
    ctx = setup_confirmed_booking(
        listing_overrides={"base_nightly_rate_cents": 20000, "cleaning_fee_cents": 5000,
                           "cancellation_tier": "FLEXIBLE", "security_deposit_cents": 0},
        booking_overrides={"check_in": "2026-07-10", "check_out": "2026-07-13"},
        clock="2026-07-01T00:00:00Z",
    )
    host, guest, listing, booking = ctx["host"], ctx["guest"], ctx["listing"], ctx["booking"]
    api.cancel_booking(booking["id"], headers=make_guest_headers(guest["id"]))
    resp = api.list_calendar_blocks(
        listing["id"], headers=make_host_headers(host["id"]), params={"status": "ACTIVE"})
    _, meta = validate_paginated(resp)
    assert meta["total_count"] == 0, \
        f"After cancel, ACTIVE block count should return to pre-booking 0, got {meta['total_count']}"


def test_cancel_releases_the_booking_block(api):
    """PRD §3.9: "In every cancellation, the booking's calendar block is released
    (its `status` becomes `RELEASED` and the booking's `calendar_block_id`
    becomes null)."

    Second test of the conservation invariant: the released block is observable
    as RELEASED via the listing's calendar-block list.

    Design: Difficulty/compensating_invariant/cancel_conserves_listing_occupied_nights
    """
    ctx = setup_confirmed_booking(
        listing_overrides={"base_nightly_rate_cents": 20000, "cleaning_fee_cents": 5000,
                           "cancellation_tier": "FLEXIBLE", "security_deposit_cents": 0},
        booking_overrides={"check_in": "2026-07-10", "check_out": "2026-07-13"},
        clock="2026-07-01T00:00:00Z",
    )
    host, guest, listing, booking = ctx["host"], ctx["guest"], ctx["listing"], ctx["booking"]
    api.cancel_booking(booking["id"], headers=make_guest_headers(guest["id"]))
    resp = api.list_calendar_blocks(
        listing["id"], headers=make_host_headers(host["id"]), params={"status": "RELEASED"})
    _, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, \
        f"Exactly one RELEASED block expected after cancel, got {meta['total_count']}"
