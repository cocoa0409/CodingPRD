"""Calculation rules (PRD §3.3, §3.7, §3.8, §3.9, §3.10, §3.11 / SCAFFOLD §1.3).

All gallons / cases are carried at full precision; monetary conversions round
half up to whole cents exactly once at the pinned step.
"""
import math
from decimal import Decimal

import constants as C
from util import round_half_up


# ---------------------------------------------------------------------------
# removal gallons (PRD §3.3) — full precision, no rounding here
# ---------------------------------------------------------------------------
def removal_gallons(requested_bottles, bottle_volume_ml):
    # requested_bottles * (bottle_volume_ml / 1000) / LITERS_PER_GALLON
    return requested_bottles * (bottle_volume_ml / 1000.0) / C.LITERS_PER_GALLON


# ---------------------------------------------------------------------------
# 1. excise_accrual (PRD §3.3) — one bottling run's gallons only
# ---------------------------------------------------------------------------
def excise_cents(beverage_class, abv_percent, gallons):
    if beverage_class == "WINE":
        if abv_percent <= C.WINE_ABV_TIER1_MAX:
            rate = C.WINE_RATE_TIER1_CENTS_PER_GAL
        else:
            rate = C.WINE_RATE_TIER2_CENTS_PER_GAL
        return round_half_up(Decimal(str(gallons)) * Decimal(rate))
    elif beverage_class == "BEER":
        barrels = Decimal(str(gallons)) / Decimal(str(C.GALLONS_PER_BEER_BARREL))
        return round_half_up(barrels * Decimal(C.BEER_RATE_CENTS_PER_BARREL))
    else:  # CIDER
        return round_half_up(Decimal(str(gallons)) * Decimal(C.CIDER_RATE_CENTS_PER_GAL))


# ---------------------------------------------------------------------------
# 2. loyalty earn (PRD §3.7, §3.9) — floor(net_spend / 100) * tier_mult
# ---------------------------------------------------------------------------
def loyalty_earned(net_spend_cents, tier):
    mult = C.LOYALTY_MULT[tier]
    return (net_spend_cents // C.CENTS_PER_POINT) * mult


# ---------------------------------------------------------------------------
# 3. shipment_pricing (PRD §3.7) — single rounding after eff_pct resolved
# ---------------------------------------------------------------------------
def shipment_pricing(requested_bottles, list_price_cents, tier):
    subtotal_cents = requested_bottles * list_price_cents
    base_pct = C.TIER_DISCOUNT_PCT[tier]
    eff_pct = base_pct + (C.VOLUME_KICKER_PCT if requested_bottles >= C.VOLUME_KICKER_BOTTLES else 0.0)
    eff_pct = min(eff_pct, C.MAX_DISCOUNT_PCT)  # cap last
    discount_cents = round_half_up(Decimal(str(subtotal_cents)) * Decimal(str(eff_pct)))
    total_cents = subtotal_cents - discount_cents
    return subtotal_cents, discount_cents, total_cents


# ---------------------------------------------------------------------------
# 4. pos_order_total (PRD §3.9) — round PER LINE then sum
# ---------------------------------------------------------------------------
def pos_order_total(lines, tier, redeem_points):
    """lines: list of dicts {kind, quantity, unit_price_cents (resolved)}.
    tier: membership tier or None (no member attached -> no discount).
    Returns (subtotal_cents, member_discount_cents, loyalty_redeemed_cents,
             total_cents, line_totals).
    """
    line_totals = []
    subtotal_cents = 0
    bottle_subtotal = 0
    for line in lines:
        ext = Decimal(str(line["quantity"])) * Decimal(str(line["unit_price_cents"]))
        line_total = round_half_up(ext)  # round PER LINE
        line_totals.append(line_total)
        subtotal_cents += line_total
        if line["kind"] == "BOTTLE":
            bottle_subtotal += line_total

    if tier is not None:
        member_discount_cents = round_half_up(
            Decimal(str(bottle_subtotal)) * Decimal(str(C.TIER_DISCOUNT_PCT[tier]))
        )
    else:
        member_discount_cents = 0

    redeem_value = redeem_points * C.REDEEM_CENTS_PER_POINT
    loyalty_redeemed_cents = min(redeem_value, subtotal_cents - member_discount_cents)
    if loyalty_redeemed_cents < 0:
        loyalty_redeemed_cents = 0

    total_cents = max(0, subtotal_cents - member_discount_cents - loyalty_redeemed_cents)
    return subtotal_cents, member_discount_cents, loyalty_redeemed_cents, total_cents, line_totals


def points_consumed(redeemed_value_cents):
    """Points actually consumed for the redeemed value (ceil)."""
    return math.ceil(redeemed_value_cents / C.REDEEM_CENTS_PER_POINT)


# ---------------------------------------------------------------------------
# 5. ship_state_limit_check (PRD §3.8) — cases at full precision, strict >
# ---------------------------------------------------------------------------
def shipment_cases(requested_bottles, bottle_volume_ml):
    return (requested_bottles * bottle_volume_ml / 1000.0) / C.LITERS_PER_9L_CASE


def state_case_limit(state_code):
    return C.STATE_CASE_LIMITS.get(state_code, C.DEFAULT_STATE_CASE_LIMIT)


def state_limit_exceeded(prior_cases, this_cases, state_code):
    """True when prior + this is STRICTLY greater than the state's limit."""
    limit = state_case_limit(state_code)
    return (prior_cases + this_cases) > limit


# ---------------------------------------------------------------------------
# 7. distribution_invoice (PRD §3.11) — freight keyed on wholesale_base
# ---------------------------------------------------------------------------
def distribution_invoice(case_count, list_price_cents):
    bottles_ordered = case_count * C.BOTTLES_PER_CASE
    gross_cents = bottles_ordered * list_price_cents
    wholesale_base = round_half_up(Decimal(str(gross_cents)) * Decimal(str(C.WHOLESALE_PCT)))
    if wholesale_base >= C.FREIGHT_TIER_THRESHOLD_CENTS:
        freight = C.FREIGHT_HIGH_CENTS
    else:
        freight = C.FREIGHT_LOW_CENTS
    wholesale_total_cents = wholesale_base + freight
    return bottles_ordered, wholesale_total_cents


# ---------------------------------------------------------------------------
# 8. event_deposit (PRD §3.10)
# ---------------------------------------------------------------------------
def event_deposit(party_size, is_event):
    return (party_size * C.EVENT_DEPOSIT_PER_GUEST_CENTS) if is_event else 0
