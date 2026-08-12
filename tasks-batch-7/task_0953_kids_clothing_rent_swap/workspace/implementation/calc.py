"""Pure derivations (SCAFFOLD calculations)."""

from decimal import Decimal

import constants as K
import timeutil
from money import D, quantize_fraction, round_half_up, round_half_up_to_step


# ---------- sizes --------------------------------------------------------

def size_ordinal(code):
    return K.SIZE_LADDER_ORDINALS[code]


def size_compatible(unit_size_code, member_size_code):
    d = size_ordinal(unit_size_code) - size_ordinal(member_size_code)
    return (d >= -K.SIZE_COMPAT_STEPS_BELOW_MAX) and (d <= K.SIZE_COMPAT_STEPS_ABOVE_MAX)


# ---------- cycle windows ------------------------------------------------

def cycle_windows(start_at):
    swap_by_at = timeutil.add_days(start_at, K.SWAP_BY_OFFSET_DAYS)
    return_due_at = timeutil.add_days(start_at, K.RETURN_DUE_OFFSET_DAYS)
    grace_ends_at = timeutil.add_days(return_due_at, K.GRACE_PERIOD_DAYS)
    return swap_by_at, return_due_at, grace_ends_at


def cycle_status_from_clock(cycle, clock):
    if clock <= cycle["swap_by_at"]:
        return "OPEN"
    if clock <= cycle["return_due_at"]:
        return "SWAP_CLOSED"
    if clock <= cycle["grace_ends_at"]:
        return "RETURN_DUE"
    return "GRACE"


# ---------- money: discounts and the cycle invoice -----------------------

def effective_discount_pct(plan, protection_enrolled):
    gross = plan["monthly_fee_cents"] + (K.PROTECTION_FEE_CENTS_PER_CYCLE if protection_enrolled else 0)
    if gross >= K.VOLUME_DISCOUNT_TIER_2_MIN_CENTS:
        tier = D(K.VOLUME_DISCOUNT_TIER_2_PCT)
    elif gross >= K.VOLUME_DISCOUNT_TIER_1_MIN_CENTS:
        tier = D(K.VOLUME_DISCOUNT_TIER_1_PCT)
    else:
        tier = D(0)
    combined = D(plan["discount_pct"]) + tier
    capped = min(D(K.DISCOUNT_PCT_MAX), combined)
    return quantize_fraction(capped, 4)


def plan_charge(plan, proration_credit_cents, fraction):
    prorated = D(plan["monthly_fee_cents"] - proration_credit_cents)
    return round_half_up(prorated * (Decimal(1) - fraction))


def protection_fee(fraction):
    return round_half_up(D(K.PROTECTION_FEE_CENTS_PER_CYCLE) * (Decimal(1) - fraction))


def protection_waiver_effective_cap(cycle):
    return round_half_up(
        D(K.PROTECTION_WAIVER_CAP_PER_CYCLE_CENTS)
        * D(cycle["protection_fee_cents"])
        / D(K.PROTECTION_FEE_CENTS_PER_CYCLE)
    )


def protection_waiver_remaining_cap(cycle):
    return max(0, protection_waiver_effective_cap(cycle) - cycle["protection_waiver_used_cents"])


def damage_fee_gross(grade, retail_price_cents):
    if grade == "RETIRE":
        return round_half_up(D(retail_price_cents) * D(K.DAMAGE_FEE_RETIRE_PCT_OF_RETAIL))
    return K.DAMAGE_FEE_BY_GRADE_CENTS[grade]


def surcharge_amount(taxable_base):
    return round_half_up(D(taxable_base) * D(K.SURCHARGE_RATE))


# ---------- late fees ----------------------------------------------------

def days_late_for(effective_instant, grace_ends_at):
    if effective_instant <= grace_ends_at:
        return 0
    return timeutil.ceil_days(effective_instant - grace_ends_at)


def late_fee_for_days(days_late, late_fee_mode):
    if late_fee_mode == "PER_DAY":
        return min(days_late * K.LATE_FEE_PER_UNIT_PER_DAY_CENTS, K.LATE_FEE_CAP_PER_UNIT_CENTS)
    if days_late == 0:
        return 0
    if days_late <= K.LATE_FEE_TIER_1_MAX_DAYS:
        return K.LATE_FEE_FLAT_TIER_1_CENTS
    if days_late <= K.LATE_FEE_TIER_2_MAX_DAYS:
        return K.LATE_FEE_FLAT_TIER_2_CENTS
    return K.LATE_FEE_FLAT_TIER_3_CENTS


# ---------- buy-out ------------------------------------------------------

def buyout_quoted_price(style, unit, variant, clock):
    base = D(style["retail_price_cents"]) * D(K.BUYOUT_BASE_RATE_BY_GRADE[unit["current_grade"]])
    if variant == "CYCLES_WORN":
        decay = Decimal(1) - (D(unit["cycles_completed"]) * D(K.BUYOUT_CYCLE_DECAY_PER_CYCLE))
    else:
        months = timeutil.floor_months(clock, unit["acquired_at"])
        decay = Decimal(1) - (D(months) * D(K.BUYOUT_MONTH_DECAY_PER_MONTH))
    decay = max(decay, D(K.BUYOUT_DECAY_FLOOR_FACTOR))
    raw = base * decay
    return round_half_up_to_step(raw, K.BUYOUT_ROUNDING_STEP_CENTS)


def buyout_late_surcharge(quoted_price_cents, days_late):
    if days_late > 0:
        return round_half_up(D(quoted_price_cents) * D(K.BUYOUT_LATE_SURCHARGE_PCT))
    return 0


def buyout_final_price(quoted_price_cents, late_surcharge_cents):
    return max(quoted_price_cents + late_surcharge_cents, K.BUYOUT_MIN_PRICE_CENTS)


# ---------- trade-in -----------------------------------------------------

def tradein_item_credit(grade, brand_tier, demand_band):
    return round_half_up(
        D(K.TRADEIN_GRADE_BASE_CENTS[grade])
        * D(K.BRAND_TIER_MULTIPLIER[brand_tier])
        * D(K.SIZE_DEMAND_BAND_MULTIPLIER[demand_band])
    )


def tradein_cap_waterfall(items, tier):
    """items: list of dicts already ordered credit_cents DESC, created_at ASC."""
    uncapped = sum(item["credit_cents"] for item in items)
    grants = {}
    if tier == "CAPSULE_PLUS":
        if uncapped <= 0:
            factor = Decimal(1)
        else:
            factor = min(Decimal(1), D(K.TRADEIN_CREDIT_CAP_PER_SUBMISSION_CENTS) / D(uncapped))
        for item in items:
            grants[item["id"]] = round_half_up(D(item["credit_cents"]) * factor)
    else:
        remaining = K.TRADEIN_CREDIT_CAP_PER_SUBMISSION_CENTS
        for item in items:
            granted = min(item["credit_cents"], remaining)
            grants[item["id"]] = granted
            remaining -= granted
    credited_total = sum(grants.values())
    return uncapped, grants, credited_total


# ---------- lost parcels -------------------------------------------------

def lost_assessed_value(units_with_styles):
    """units_with_styles: iterable of (unit, style) already ordered created_at ASC."""
    total = 0
    for _unit, style in units_with_styles:
        total += round_half_up(D(style["retail_price_cents"]) * D(K.LOST_ASSESSED_VALUE_PCT_OF_RETAIL))
    return total


def lost_liability(assessed_value_cents, ever_scanned):
    pct = K.LOST_LIABILITY_MEMBER_PCT_SCANNED if ever_scanned else K.LOST_LIABILITY_MEMBER_PCT_NEVER_SCANNED
    cents = round_half_up(D(assessed_value_cents) * D(pct))
    return float(D(pct)), cents


# ---------- pause proration ---------------------------------------------

def pause_proration(plan, overlap_days):
    basis = K.PAUSE_PRORATION_DAY_BASIS if plan["proration_basis"] == "THIRTY_DAY" else K.CYCLE_LENGTH_DAYS
    credit = round_half_up(D(plan["monthly_fee_cents"]) * D(overlap_days) / D(basis))
    return min(credit, plan["monthly_fee_cents"])


# ---------- processing ---------------------------------------------------

def rework_increment(route):
    return round_half_up(D(K.ROUTE_BASE_COST_CENTS[route]) * D(K.REWORK_COST_MULTIPLIER))
