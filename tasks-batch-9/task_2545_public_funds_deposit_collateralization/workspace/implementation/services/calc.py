"""Pure arithmetic and the calculation rules of PRD 3.

All money is whole cents held in Python ints; all rates are whole basis points.
Decimal is used for the rounding primitives so that no float ever touches a
monetary value.
"""

from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

import db
from constants import (
    ADEQUATELY_CAPITALIZED_MIN_BPS,
    CAPITAL_TIER_BASE_PCT_BPS,
    COVERAGE_COMPONENT_FLOOR_BPS,
    COVERAGE_COMPONENT_SPAN_BPS,
    COVERAGE_RATIO_CAP_BPS,
    CURE_WINDOW_DEFAULT_HOURS,
    CURE_WINDOW_TIERS,
    DEFICIENCY_SURCHARGE_BPS,
    DEFICIENCY_SURCHARGE_MIN_RUNS,
    HAIRCUT_BPS_BY_ASSET_TYPE,
    INSURANCE_COVERAGE_LIMIT_CENTS,
    PLEDGING_MODE_SURCHARGE_BPS,
    REQUIRED_PCT_CEILING_BPS,
    RISK_GRADE_THRESHOLDS,
    RISK_WEIGHT_COVERAGE,
    RISK_WEIGHT_DOCUMENTATION,
    RISK_WEIGHT_VOLATILITY,
    VOLATILITY_PENALTY_PER_RUN_BPS,
    WELL_CAPITALIZED_MIN_BPS,
)


# ---------------------------------------------------------------------------
# Rounding primitives (PRD 2.5)
# ---------------------------------------------------------------------------
def round_half_up(numerator, denominator):
    """Round numerator/denominator half up (away from zero) to a whole unit."""
    return int(
        (Decimal(numerator) / Decimal(denominator)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    )


def floor_div(numerator, denominator):
    """Truncate numerator/denominator toward zero to a whole unit."""
    return int(
        (Decimal(numerator) / Decimal(denominator)).quantize(Decimal(1), rounding=ROUND_FLOOR)
    )


def scale_bps(amount, bps):
    """A cent amount scaled by a basis-point figure, rounded half up."""
    return round_half_up(amount * bps, 10000)


# ---------------------------------------------------------------------------
# Valuation (PRD 3.4) — two sequential rounding steps, in this order
# ---------------------------------------------------------------------------
def haircut_for(asset_type):
    return HAIRCUT_BPS_BY_ASSET_TYPE.get(asset_type, 0)


def market_value(par_cents, market_price_bps):
    return scale_bps(par_cents, market_price_bps)


def haircut_value(par_cents, market_price_bps, haircut_bps):
    return scale_bps(market_value(par_cents, market_price_bps), 10000 - haircut_bps)


def asset_value_of_par(asset, par_cents):
    return haircut_value(par_cents, asset["market_price_bps"], asset["haircut_bps"])


# ---------------------------------------------------------------------------
# Intervals
# ---------------------------------------------------------------------------
def covers(allocation, moment):
    """Half-open interval test: effective_from <= moment < effective_to."""
    return allocation["effective_from"].dt <= moment < allocation["effective_to"].dt


# ---------------------------------------------------------------------------
# Insurance determination (PRD 3.2) — two variants
# ---------------------------------------------------------------------------
def apply_insurance(members, basis):
    """Assign insured/uninsured amounts over one insurance group, in the
    group_sequence ASC order the caller supplies."""
    remaining = INSURANCE_COVERAGE_LIMIT_CENTS
    for account in members:
        balance = account["ledger_balance_cents"]
        if basis == "PER_ACCOUNT":
            insured = min(INSURANCE_COVERAGE_LIMIT_CENTS, balance)
        else:
            insured = min(remaining, balance)
            remaining -= insured
        account["insured_amount_cents"] = insured
        account["uninsured_amount_cents"] = balance - insured


# ---------------------------------------------------------------------------
# Required collateral percentage (PRD 3.2)
# ---------------------------------------------------------------------------
def capital_tier(capital_ratio_bps):
    if capital_ratio_bps >= WELL_CAPITALIZED_MIN_BPS:
        return "WELL_CAPITALIZED"
    if capital_ratio_bps >= ADEQUATELY_CAPITALIZED_MIN_BPS:
        return "ADEQUATELY_CAPITALIZED"
    return "UNDERCAPITALIZED"


def deficiency_surcharge_bps(counter):
    return DEFICIENCY_SURCHARGE_BPS if counter >= DEFICIENCY_SURCHARGE_MIN_RUNS else 0


def required_pct_bps(depository, pledging_mode, deficiency_counter):
    base = CAPITAL_TIER_BASE_PCT_BPS[capital_tier(depository["capital_ratio_bps"])]
    mode = PLEDGING_MODE_SURCHARGE_BPS.get(pledging_mode, 0)
    total = base + mode + deficiency_surcharge_bps(deficiency_counter)
    return min(REQUIRED_PCT_CEILING_BPS, total)


def required_collateral_cents(uninsured_amount_cents, pct_bps):
    return scale_bps(uninsured_amount_cents, pct_bps)


def coverage_ratio_bps(assigned_cents, required_cents):
    if required_cents == 0:
        return 10000
    return floor_div(assigned_cents * 10000, required_cents)


def next_collateral_status(current, assigned_cents, required_cents, ratio_bps):
    """The six transitions of PRD 3.2, applied to the account's current state."""
    if current == "UNSECURED":
        if ratio_bps >= 10000:
            return "SECURED"
        if assigned_cents > 0:
            return "DEFICIENT"
        return "UNSECURED"
    if current == "SECURED":
        if assigned_cents == 0 and required_cents > 0:
            return "UNSECURED"
        if ratio_bps < 10000 and assigned_cents > 0:
            return "DEFICIENT"
        return "SECURED"
    if current == "DEFICIENT":
        if ratio_bps >= 10000:
            return "SECURED"
        if assigned_cents == 0 and required_cents > 0:
            return "UNSECURED"
        return "DEFICIENT"
    return current


def exposure_status(accounts):
    """Strictly ordered read: restriction dominates deficiency (PRD 3.1)."""
    if any(a["funding_status"] == "RESTRICTED" for a in accounts):
        return "ESCALATED"
    if any(a["collateral_status"] == "DEFICIENT" for a in accounts):
        return "WATCH"
    return "NORMAL"


# ---------------------------------------------------------------------------
# Mark-to-market scoring (PRD 3.7)
# ---------------------------------------------------------------------------
def deficiency_ratio_bps(deficiency_cents, total_required_cents):
    if total_required_cents == 0:
        return 0
    return floor_div(deficiency_cents * 10000, total_required_cents)


def cure_window_hours(ratio_bps):
    for threshold, hours in CURE_WINDOW_TIERS:
        if ratio_bps >= threshold:
            return hours
    return CURE_WINDOW_DEFAULT_HOURS


def coverage_component_bps(total_value_cents, total_required_cents):
    if total_required_cents == 0:
        capped = COVERAGE_RATIO_CAP_BPS
    else:
        capped = min(
            COVERAGE_RATIO_CAP_BPS,
            floor_div(total_value_cents * 10000, total_required_cents),
        )
    raw = round_half_up((capped - COVERAGE_COMPONENT_FLOOR_BPS) * 10000, COVERAGE_COMPONENT_SPAN_BPS)
    return max(0, min(10000, raw))


def volatility_component_bps(consecutive_deficiency_runs):
    return 10000 - min(10000, consecutive_deficiency_runs * VOLATILITY_PENALTY_PER_RUN_BPS)


def documentation_component_bps(numerator, denominator):
    if denominator == 0:
        return 10000
    return min(10000, round_half_up(10000 * numerator, denominator))


def mean_bps(values):
    return round_half_up(sum(values), len(values))


def risk_score_bps(coverage, volatility, documentation):
    weighted = (
        RISK_WEIGHT_COVERAGE * coverage
        + RISK_WEIGHT_VOLATILITY * volatility
        + RISK_WEIGHT_DOCUMENTATION * documentation
    )
    return round_half_up(weighted, 100)


def risk_grade_for(score_bps):
    for grade, threshold in RISK_GRADE_THRESHOLDS:
        if score_bps >= threshold:
            return grade
    return "D"


# ---------------------------------------------------------------------------
# Runoff projection (PRD 3.9)
# ---------------------------------------------------------------------------
def window_requirement_cents(projected_balance_cents, pct_bps):
    uninsured = max(0, projected_balance_cents - INSURANCE_COVERAGE_LIMIT_CENTS)
    return scale_bps(uninsured, pct_bps)


def unpledged_capacity_cents(assets):
    total = 0
    for asset in assets:
        if asset["eligibility_status"] != "ELIGIBLE":
            continue
        if asset["available_par_cents"] <= 0:
            continue
        total += haircut_value(
            asset["available_par_cents"], asset["market_price_bps"], asset["haircut_bps"]
        )
    return total


def hours_stale(priced_at):
    return db.hours_between(priced_at.dt, db.clock())
