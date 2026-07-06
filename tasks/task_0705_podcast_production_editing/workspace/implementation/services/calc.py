"""Calculation rules (PRD §3.5-§3.8, §3.10 / scaffold §1.3).

All money is integer cents. Percentage products are rounded half-up to whole
cents (Python's round() uses banker's rounding, so we use Decimal ROUND_HALF_UP).
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    DISCOUNT_CAP_CENTS,
    EXTRA_TRACK_FLOOR,
    EXTRA_TRACK_RATE_CENTS,
    GOLD_THRESHOLD_CENTS,
    LATE_FEE_PCT,
    MULTITRACK_FLOOR_TRACKS,
    OVERAGE_RATE_CENTS,
    SILVER_THRESHOLD_CENTS,
    SURCHARGE_HOURS_PER_TRACK,
    TIER_BASE_CENTS,
    TIER_SLA_HOURS,
    TRANSCRIPT_CENTS,
)


def round_half_up(value):
    """Round a numeric value half-up to the nearest integer (cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def sla_hours(tier, track_count):
    """SLA hours = tier base + surcharge for tracks beyond the multitrack floor."""
    surcharge = max(0, track_count - MULTITRACK_FLOOR_TRACKS) * SURCHARGE_HOURS_PER_TRACK
    return TIER_SLA_HOURS[tier] + surcharge


def turnaround_due(anchor, tier, track_count):
    """anchor + hours(sla_hours(track_count)) (PRD §3.6)."""
    return anchor + timedelta(hours=sla_hours(tier, track_count))


def late_fee_tier(snapshot_cents):
    """Tier from the lifetime_billed snapshot taken BEFORE this invoice (PRD §3.7)."""
    if snapshot_cents >= GOLD_THRESHOLD_CENTS:
        return "GOLD"
    if snapshot_cents >= SILVER_THRESHOLD_CENTS:
        return "SILVER"
    return "BRONZE"


def late_fee_cents(subtotal_cents, discount_cents, delivered_late, snapshot_cents):
    """Late fee = (subtotal - discount) * tier rate, round-half-up; 0 if not late."""
    if not delivered_late:
        return 0
    tier = late_fee_tier(snapshot_cents)
    base = subtotal_cents - discount_cents
    return round_half_up(base * LATE_FEE_PCT[tier])


def per_episode_invoice_amounts(tier, transcript_requested, raw_track_count,
                                loyalty_discount_pct, delivered_late, snapshot_cents):
    """Compute (subtotal, discount, late_fee, total) for a PER_EPISODE invoice.

    PRD §3.5 / calc invoice_total + late_fee. Snapshot ordering pinned (§2.9):
    the late-fee tier is keyed on the lifetime snapshot taken BEFORE this invoice.
    """
    base_cents = TIER_BASE_CENTS[tier]
    transcript_cents = TRANSCRIPT_CENTS if transcript_requested else 0
    extra_track_cents = max(0, raw_track_count - EXTRA_TRACK_FLOOR) * EXTRA_TRACK_RATE_CENTS
    subtotal = base_cents + transcript_cents + extra_track_cents
    raw_discount = round_half_up(subtotal * loyalty_discount_pct)
    discount = min(raw_discount, DISCOUNT_CAP_CENTS)
    late_fee = late_fee_cents(subtotal, discount, delivered_late, snapshot_cents)
    total = subtotal - discount + late_fee
    return subtotal, discount, late_fee, total


def overage_invoice_amounts(tier, overage_episode_count, loyalty_discount_pct,
                            delivered_late, snapshot_cents):
    """Compute (subtotal, discount, late_fee, total) for a RETAINER_OVERAGE invoice.

    PRD §3.8: subtotal = overage_count * tier overage rate; then discount, late
    fee, total computed as for any invoice. Retainer-overage delivery is never
    flagged late (no per-episode delivered_late applies), so delivered_late is
    passed false by the caller.
    """
    subtotal = overage_episode_count * OVERAGE_RATE_CENTS[tier]
    raw_discount = round_half_up(subtotal * loyalty_discount_pct)
    discount = min(raw_discount, DISCOUNT_CAP_CENTS)
    late_fee = late_fee_cents(subtotal, discount, delivered_late, snapshot_cents)
    total = subtotal - discount + late_fee
    return subtotal, discount, late_fee, total


def ad_revenue_split(slots, platform_fee_pct):
    """Per-slot round-half-up of the show share, then sum (PRD §3.10).

    Returns (show_payout_cents, platform_take_cents).
    """
    keep = 1 - platform_fee_pct
    show_payout = sum(round_half_up(slot["gross_cents"] * keep) for slot in slots)
    gross_total = sum(slot["gross_cents"] for slot in slots)
    platform_take = gross_total - show_payout
    return show_payout, platform_take
