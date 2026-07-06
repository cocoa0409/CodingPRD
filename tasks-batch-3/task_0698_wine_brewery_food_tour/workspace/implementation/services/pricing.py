"""Pricing, gratuity, refund, and commission calculations.

All money is integer cents, rounded half-up (PRD §2.6 / §3.7; SCAFFOLD
calculations). Evaluation orders are pinned exactly as the PRD describes.
"""
from decimal import Decimal
from util import round_half_up_money

# Group-size discount tiers (PRD §3.7 / SCAFFOLD booking_price_quote).
TIER_12_PCT = Decimal("0.15")
TIER_8_PCT = Decimal("0.10")
TIER_4_PCT = Decimal("0.05")
TIER_0_PCT = Decimal("0.00")

# Refund lead-time thresholds (PRD §3.7 / SCAFFOLD cancellation_refund).
FULL_REFUND_HOURS = 168  # >= 7 days
HALF_REFUND_HOURS = 48   # >= 48h and < 168h


def discount_tier(party_size):
    """Select the per-person base discount by party_size against descending
    thresholds (>= boundaries): >=12 -> 0.15; >=8 -> 0.10; >=4 -> 0.05; else 0.
    """
    if party_size >= 12:
        return TIER_12_PCT
    if party_size >= 8:
        return TIER_8_PCT
    if party_size >= 4:
        return TIER_4_PCT
    return TIER_0_PCT


def quote(base_price_per_person_cents, party_size, addon_price_per_person_cents,
          is_charter, charter_fee_cents, gratuity_pct):
    """Compute the booking price quote (PRD §3.7).

    Returns a dict with seats_total_cents, addon_total_cents, charter_cents,
    subtotal_cents, gratuity_cents, total_cents.

    Pinned order:
      1) tier discount on per-person BASE only (not add-ons, not charter)
      2) round the discounted PER-PERSON fare half-up FIRST, THEN multiply by
         party_size  (round-then-multiply — must not be reversed)
      3) gratuity base = seats_total + addon_total  (charter EXCLUDED)
      4) gratuity = round_half_up(gratuity_base * gratuity_pct)
      5) total = subtotal + gratuity
    """
    tier_pct = discount_tier(party_size)
    # round per-person first
    disc_pp_cents = round_half_up_money(
        Decimal(base_price_per_person_cents) * (Decimal(1) - tier_pct))
    seats_total_cents = disc_pp_cents * party_size

    addon_total_cents = (addon_price_per_person_cents * party_size
                         if addon_price_per_person_cents is not None else 0)

    charter_cents = charter_fee_cents if is_charter else 0

    subtotal_cents = seats_total_cents + addon_total_cents + charter_cents

    # gratuity base deliberately excludes the charter fee
    gratuity_base_cents = seats_total_cents + addon_total_cents
    gratuity_cents = round_half_up_money(
        Decimal(gratuity_base_cents) * Decimal(str(gratuity_pct)))

    total_cents = subtotal_cents + gratuity_cents

    return {
        "seats_total_cents": seats_total_cents,
        "addon_total_cents": addon_total_cents,
        "charter_cents": charter_cents,
        "subtotal_cents": subtotal_cents,
        "gratuity_cents": gratuity_cents,
        "total_cents": total_cents,
    }


def commission(headcount, tasting_cost_per_guest_cents, commission_pct):
    """Per-stop commission = round_half_up(headcount * tasting_cost * pct).

    Used by both estimated and settled variants; only the headcount differs
    (PRD §3.7 / SCAFFOLD partner_commission).
    """
    return round_half_up_money(
        Decimal(headcount)
        * Decimal(tasting_cost_per_guest_cents)
        * Decimal(str(commission_pct)))


def refund(amount_paid_cents, hours_before, weather_override):
    """Lead-time tiered refund (PRD §3.7).

    weather_override -> 100%. Else: >=168h -> 100%; >=48h and <168h -> 50%;
    <48h -> 0%. Boundaries inclusive on the lower edge.
    """
    if weather_override:
        refund_pct = Decimal("1.00")
    elif hours_before >= FULL_REFUND_HOURS:
        refund_pct = Decimal("1.00")
    elif hours_before >= HALF_REFUND_HOURS:
        refund_pct = Decimal("0.50")
    else:
        refund_pct = Decimal("0.00")
    return round_half_up_money(Decimal(amount_paid_cents) * refund_pct)


def hours_before(depart_at, clock_now):
    """Hours between clock_now and depart_at (PRD §3.7). May be fractional."""
    delta_seconds = (depart_at - clock_now).total_seconds()
    return delta_seconds / 3600.0
