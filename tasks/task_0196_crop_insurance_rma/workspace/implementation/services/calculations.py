"""Domain calculations (PRD §3.3, §3.4, §3.7, §3.8 / scaffold §1.3).

All money is integer cents, round-half-up. Per-acre amounts are rounded to whole
cents BEFORE multiplying by acreage where the PRD pins that order.
"""
from services.common import round_half_up_int, round_half_up_2

# Plan loading multiplier (PRD §3.4)
RATE_MULTIPLIER = {"YP": 1.00, "RP": 1.15, "RP_HPE": 1.08}

# Federal subsidy table — exact coverage_level key lookup, no interpolation (PRD §3.4)
SUBSIDY_FACTORS = {
    0.50: 0.67,
    0.55: 0.64,
    0.60: 0.64,
    0.65: 0.59,
    0.70: 0.59,
    0.75: 0.55,
    0.80: 0.48,
    0.85: 0.38,
}

ALLOWED_COVERAGE_LEVELS = set(SUBSIDY_FACTORS.keys())


def _coverage_key(coverage_level):
    """Match coverage_level to a table key robustly against float repr."""
    for k in SUBSIDY_FACTORS:
        if abs(k - coverage_level) < 1e-9:
            return k
    return None


def subsidy_factor_for(coverage_level):
    k = _coverage_key(coverage_level)
    return SUBSIDY_FACTORS[k]


# ---- yield_guarantee_and_liability (PRD §3.3) -------------------------------
def yield_guarantee_bu(aph_yield, coverage_level):
    return round_half_up_2(aph_yield * coverage_level)


def dollar_liability_per_acre_cents(guarantee_bu, projected_price):
    return round_half_up_int(guarantee_bu * projected_price * 100)


# ---- total_premium (PRD §3.4) ----------------------------------------------
def per_acre_premium_cents(liability_per_acre_cents, base_premium_rate, plan_type):
    """Round per-acre premium to whole cents FIRST (before applying acreage)."""
    raw = liability_per_acre_cents * base_premium_rate * RATE_MULTIPLIER[plan_type]
    return round_half_up_int(raw)


def unit_premium_cents(per_acre_cents, acres, share):
    return round_half_up_int(per_acre_cents * acres * share)


# ---- subsidy_split (PRD §3.4) ----------------------------------------------
def subsidy_split(total_premium_cents, coverage_level):
    factor = subsidy_factor_for(coverage_level)
    subsidy_cents = round_half_up_int(total_premium_cents * factor)
    producer_premium_cents = total_premium_cents - subsidy_cents
    return subsidy_cents, producer_premium_cents


# ---- yp_or_rp_indemnity (PRD §3.7) -----------------------------------------
def yp_or_rp_indemnity_cents(plan_type, guarantee_bu, production_to_count_bu,
                             acres, share, projected_price, harvest_price):
    insured_acres = acres
    ptc_per_acre = production_to_count_bu / insured_acres
    if plan_type == "YP":
        # Yield loss priced at projected price; harvest_price ignored.
        indemnity_per_acre = max(0.0, guarantee_bu - ptc_per_acre) * projected_price
    else:
        # Revenue loss. RP uses max(projected, harvest) for the guarantee;
        # RP_HPE excludes harvest upside (projected only). Calculated revenue
        # always uses harvest_price.
        if plan_type == "RP":
            rp_price = max(projected_price, harvest_price)
        else:  # RP_HPE
            rp_price = projected_price
        revenue_guarantee_per_acre = guarantee_bu * rp_price
        calculated_revenue_per_acre = ptc_per_acre * harvest_price
        indemnity_per_acre = max(0.0, revenue_guarantee_per_acre - calculated_revenue_per_acre)
    return round_half_up_int(indemnity_per_acre * insured_acres * share * 100)


# ---- prevented_planting_indemnity (PRD §3.8) -------------------------------
def pp_indemnity_cents(liability_per_acre_cents, pp_coverage_factor,
                       claimed_prevented_acres, share):
    per_acre = round_half_up_int(liability_per_acre_cents * pp_coverage_factor)
    return round_half_up_int(per_acre * claimed_prevented_acres * share)


# ---- agent_commission (PRD §3.8) -------------------------------------------
def commission_rate_for(total_premium_cents):
    tp = total_premium_cents
    if tp < 500000:
        return 0.10
    elif tp <= 1000000:
        return 0.08
    else:
        return 0.06


def commission_cents(total_premium_cents):
    rate = commission_rate_for(total_premium_cents)
    return rate, round_half_up_int(total_premium_cents * rate)
