"""Pure pricing/charge calculations (PRD §3.4, §3.8; SCAFFOLD §1.3).

All money is whole integer cents; rates are per 1000 gallons. Round-half-up is
applied exactly at the points the PRD specifies (§2.6).
"""
from decimal import Decimal

from services.common import round_half_up


def tiered_water_volumetric(total_gallons, water_tiers):
    """Marginal/cumulative tiered water charge over combined consumption.

    PRD §3.4 (Water volumetric charge): walk tiers ascending; each tier prices
    the slice of consumption that falls in its band (span = remaining capped at
    ceiling - prev_ceiling; terminal null tier absorbs the rest). Accumulate
    per-tier products (cents*gallons) WITHOUT rounding, then divide by 1000 and
    round half up exactly ONCE at the end.
    """
    remaining = total_gallons
    prev_ceiling = 0
    charge = 0  # units: cents * gallons
    for tier in water_tiers:
        if remaining <= 0:
            break
        ceiling = tier.get("up_to_gallons")
        if ceiling is None:
            span = remaining
        else:
            span = min(remaining, ceiling - prev_ceiling)
            if span < 0:
                span = 0
        charge += span * tier["rate_cents_per_kgal"]
        remaining -= span
        prev_ceiling = ceiling if ceiling is not None else prev_ceiling
    # Sum-then-round: divide accumulated (cents*gallons) by 1000, round once.
    return round_half_up(Decimal(charge) / Decimal(1000))


def billable_sewer_gallons(potable_gallons, sewer_ratio_pct, sewer_cap_gallons):
    """PRD §3.4 (Sewer volumetric charge), stage 1.

    ratio_volume = round_half_up(potable * ratio_pct / 100). Then apply the
    optional winter cap: min(ratio_volume, cap) when a cap is supplied, else the
    ratio volume unchanged. Irrigation never contributes (caller passes potable
    only).
    """
    ratio_volume = round_half_up(Decimal(potable_gallons * sewer_ratio_pct) / Decimal(100))
    if sewer_cap_gallons is not None:
        return min(ratio_volume, sewer_cap_gallons)
    return ratio_volume


def sewer_volumetric_cents(billable_gallons, sewer_rate_cents_per_kgal):
    """PRD §3.4: billable_sewer_gallons * sewer_rate / 1000, round half up."""
    return round_half_up(
        Decimal(billable_gallons * sewer_rate_cents_per_kgal) / Decimal(1000)
    )


def fixed_charge_cents(fixed_water, fixed_sewer, assistance_enrolled, assistance_discount_pct):
    """PRD §3.4 (Fixed charge).

    Sum of fixed water + fixed sewer. If enrolled in assistance, multiply the
    combined fixed charge by (1 - discount_pct/100), round half up. Else full sum.
    """
    combined = fixed_water + fixed_sewer
    if assistance_enrolled:
        return round_half_up(
            Decimal(combined) * (Decimal(100) - Decimal(assistance_discount_pct)) / Decimal(100)
        )
    return combined


def amount_billed_cents(fixed_charge, water_vol, sewer_vol, leak_credit):
    """PRD §3.4: fixed + water_volumetric + sewer_volumetric - leak_credit,
    floored at zero."""
    return max(0, fixed_charge + water_vol + sewer_vol - leak_credit)


def leak_credit_cents(potable_gallons, baseline_gallons, water_tiers,
                      leak_adjustment_rate_pct, bill_water_volumetric_cents):
    """PRD §3.8 (leak credit on approval).

    over_baseline = max(0, potable - baseline). Price at the LOWEST tier's rate,
    scaled by leak_adjustment_rate_pct: over_baseline * lowest_rate *
    (pct/100) / 1000, round half up. Then cap at the bill's water_volumetric_cents.
    """
    over_baseline = max(0, potable_gallons - baseline_gallons)
    lowest_rate = water_tiers[0]["rate_cents_per_kgal"]
    credit = round_half_up(
        Decimal(over_baseline)
        * Decimal(lowest_rate)
        * Decimal(leak_adjustment_rate_pct)
        / Decimal(100)
        / Decimal(1000)
    )
    return min(credit, bill_water_volumetric_cents)
