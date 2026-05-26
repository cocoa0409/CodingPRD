"""Sitter tier-score recompute + cascade helpers."""
from __future__ import annotations

import db
from services.calculations import (
    compute_sitter_tier,
    compute_booking_quote,
    compute_sitter_payout_provisional,
    tier_dropped,
)
from services.common import bump


def recompute_sitter_tier(sitter: dict, *, force_bump: bool = False) -> bool:
    """Recompute tier_score + tier on `sitter`.

    Returns True if tier_score or tier changed (and thus version was bumped).

    `force_bump=True` causes a version bump even if tier_score/tier are unchanged
    — used when called as a side-effect of a transition that already needs the
    bump for its own reasons (then the caller usually handles bumps itself).
    """
    new_score, new_tier = compute_sitter_tier(
        total_completed_bookings=sitter["total_completed_bookings"],
        total_rating_sum=sitter["total_rating_sum"],
        total_rating_count=sitter["total_rating_count"],
        claim_count=sitter["claim_count"],
    )
    changed = sitter["tier_score"] != new_score or sitter["tier"] != new_tier
    sitter["tier_score"] = new_score
    sitter["tier"] = new_tier
    if changed or force_bump:
        bump(sitter)
    return changed


def cascade1_bg_check_flagged(sitter: dict) -> None:
    """Cascade #1 — Background-check flagged.

    Move sitter to SUSPENDED (from BG_CHECK_PENDING or ACTIVE), auto-cancel
    affected bookings, restore owner wallet credit, reverse pending payouts.
    """
    # Link 2: Sitter -> SUSPENDED
    if sitter["status"] in ("BG_CHECK_PENDING", "ACTIVE"):
        sitter["status"] = "SUSPENDED"
        sitter["suspended_at"] = db.fmt_ts(db.utcnow())
        bump(sitter)

    # Link 3: auto-cancel all affected bookings
    affected_statuses = {"REQUESTED", "CONFIRMED", "KEY_RECEIVED"}
    for booking in db.bookings.values():
        if booking["sitter_id"] != sitter["id"]:
            continue
        if booking["status"] not in affected_statuses:
            continue
        original_status = booking["status"]
        booking["status"] = "CANCELLED"
        booking["cancellation_reason"] = "AUTO_SITTER_SUSPENDED"
        bump(booking)

        # Link 4: refund Owner wallet
        owner = db.owners.get(booking["owner_id"])
        if owner is not None:
            # Net effect: wallet += booking_quote_cents
            owner["wallet_credit_cents"] = (
                owner["wallet_credit_cents"] + booking["booking_quote_cents"]
            )
            bump(owner)

        # Reduce sitter pending payout for any CONFIRMED/KEY_RECEIVED booking
        # (scaffold says CONFIRMED, but KEY_RECEIVED also has the reservation
        # because the provisional payout was set at CONFIRM and never released).
        if original_status in ("CONFIRMED", "KEY_RECEIVED"):
            sitter["pending_payout_cents"] = max(
                0,
                sitter["pending_payout_cents"]
                - booking["provisional_sitter_payout_cents"],
            )
            bump(sitter)


def cascade2_claim_paid(sitter: dict) -> None:
    """Cascade #2 — Insurance claim PAID.

    Increment sitter.claim_count, recompute tier, optionally re-quote upcoming
    bookings if tier dropped, and possibly suspend sitter if claim_count >= 2.
    """
    old_tier = sitter["tier"]
    sitter["claim_count"] += 1
    bump(sitter)

    # Recompute tier
    recompute_sitter_tier(sitter)
    new_tier = sitter["tier"]

    # Link 3: tier dropped -> re-quote upcoming bookings
    if tier_dropped(old_tier, new_tier):
        for booking in db.bookings.values():
            if booking["sitter_id"] != sitter["id"]:
                continue
            if booking["status"] not in ("REQUESTED", "CONFIRMED"):
                continue
            old_quote = booking["booking_quote_cents"]
            new_quote = compute_booking_quote(
                service_type=booking["service_type"],
                sitter_tier=new_tier,
                time_of_day=booking["time_of_day"],
                recurring_cadence=booking["recurring_cadence"],
                emergency_surcharge_cents=booking["emergency_surcharge_cents"],
            )
            booking["booking_quote_cents"] = new_quote

            if booking["status"] == "CONFIRMED":
                old_provisional = booking["provisional_sitter_payout_cents"]
                new_provisional = compute_sitter_payout_provisional(new_quote)
                booking["provisional_sitter_payout_cents"] = new_provisional
                # Adjust sitter pending payout by the delta
                delta = new_provisional - old_provisional
                sitter["pending_payout_cents"] = max(
                    0, sitter["pending_payout_cents"] + delta
                )
                bump(sitter)
            bump(booking)

    # Link 4: claim_count crosses 2 while ACTIVE -> SUSPENDED
    if sitter["claim_count"] >= 2 and sitter["status"] == "ACTIVE":
        sitter["status"] = "SUSPENDED"
        sitter["suspended_at"] = db.fmt_ts(db.utcnow())
        bump(sitter)
