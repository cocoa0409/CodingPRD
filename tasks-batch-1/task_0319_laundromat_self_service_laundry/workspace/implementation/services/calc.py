"""Calculation rules (SCAFFOLD §1.3 / PRD §2.6, §3).

All monetary amounts are integer cents (PRD §2.6). Two rounding conventions:
  - surge multiplication on a vend quote and rush surcharge on a WDF order:
    round half up to the nearest whole cent.
  - loyalty-point counts and reload bonuses: floored (truncated toward zero).
"""
from decimal import Decimal, ROUND_HALF_UP

BPS_DENOM = 10000
RUSH_BPS = 2500


def round_half_up(numerator, denominator):
    """Integer-cents round-half-up of numerator/denominator."""
    q = Decimal(numerator) / Decimal(denominator)
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_div(numerator, denominator):
    """Floor (truncate toward zero for non-negative inputs)."""
    return numerator // denominator


# ---- (1) vend quote — forward-looking variant -------------------------------
def vend_quote_cents(plan, machine, dry_blocks, hour_utc):
    """Compute quoted_amount_cents and surge_applied (PRD §3.3, SCAFFOLD calc 1).

    Priced from the active plan and surge clock BEFORE any free-credit/loyalty
    adjustment.
    """
    if machine["machine_type"] == "WASHER":
        base = plan["wash_base_cents"]
    else:  # DRYER
        base = plan["dry_base_cents_per_block"] * dry_blocks
    in_surge = plan["surge_start_hour_utc"] <= hour_utc < plan["surge_end_hour_utc"]
    if in_surge:
        quoted = round_half_up(base * plan["surge_multiplier_bps"], BPS_DENOM)
    else:
        quoted = base  # multiplier effectively 10000
    return quoted, in_surge


# ---- (3) reload bonus — tiered/threshold ------------------------------------
def reload_bonus_cents(plan, principal_cents):
    """Single-tier (highest satisfied) bonus selection; tiers do not stack.

    Returns (bonus_cents, credited_cents). (PRD §3.4, SCAFFOLD calc 3)
    """
    if principal_cents >= plan["reload_bonus_tier2_min_cents"]:
        bonus_bps = plan["reload_bonus_tier2_bps"]
    elif principal_cents >= plan["reload_bonus_tier1_min_cents"]:
        bonus_bps = plan["reload_bonus_tier1_bps"]
    else:
        bonus_bps = 0
    bonus = floor_div(principal_cents * bonus_bps, BPS_DENOM)
    credited = principal_cents + bonus
    return bonus, credited


# ---- (4) WDF total — weight pricing with floor + rush -----------------------
def wdf_total_cents(plan, weight_lb, rush):
    """Pinned order: raw -> apply minimum floor -> rush on the floored subtotal.

    (PRD §3.5, SCAFFOLD calc 4)
    """
    raw = weight_lb * plan["wdf_rate_cents_per_lb"]
    floored = max(raw, plan["wdf_minimum_cents"])
    if rush:
        total = floored + round_half_up(floored * RUSH_BPS, BPS_DENOM)
    else:
        total = floored
    return total
