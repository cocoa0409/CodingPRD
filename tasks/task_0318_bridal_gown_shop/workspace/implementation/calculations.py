"""Calculation rules (PRD §3.3, §3.5, §3.6, §3.7). Integer-cent arithmetic only."""
import math

# Constants (scaffold §1.3).
SIZE_UPCHARGE_FLOOR = 20
SIZE_UPCHARGE_PCT = 0.15
RUSH_SURCHARGE_PCT = 0.30
LABOR_RATE_CENTS_PER_MIN = 120
REFIT_SURCHARGE_PCT = 0.10
DEPOSIT_FLOOR_PCT = 0.50


def _ceil_pct(base_cents, pct):
    """ceil(base_price_cents * pct) on an integer-cent base.

    Use exact integer arithmetic to avoid float drift: pct values are hundredths
    (0.15, 0.30, 0.50) and tenths-driven (0.10). Scale to integers before ceil.
    """
    # Represent pct as an exact fraction num/den.
    # 0.15 -> 15/100, 0.30 -> 30/100, 0.50 -> 50/100, 0.10 -> 10/100
    num = round(pct * 100)
    den = 100
    return math.ceil((base_cents * num) / den)


def gown_subtotal_cents(base_price_cents, ordered_size, is_rush):
    """Gown subtotal: base + per-term-ceil'd size upcharge + rush surcharge."""
    size_upcharge = (
        _ceil_pct(base_price_cents, SIZE_UPCHARGE_PCT)
        if ordered_size >= SIZE_UPCHARGE_FLOOR
        else 0
    )
    rush_surcharge = _ceil_pct(base_price_cents, RUSH_SURCHARGE_PCT) if is_rush else 0
    return base_price_cents + size_upcharge + rush_surcharge


def quoted_total_cents(base_price_cents, ordered_size, is_rush):
    """Quoted estimate at draft creation: gown subtotal only (no accessories)."""
    return gown_subtotal_cents(base_price_cents, ordered_size, is_rush)


def final_total_cents(base_price_cents, ordered_size, is_rush, active_accessory_prices):
    """Final per-line-rounded total: gown subtotal + sum of ACTIVE accessory lines."""
    subtotal = gown_subtotal_cents(base_price_cents, ordered_size, is_rush)
    return subtotal + sum(active_accessory_prices)


def estimated_alteration_cost_cents(estimated_labor_minutes):
    """Estimate variant: minutes * rate (refitting_count == 0 at creation)."""
    return estimated_labor_minutes * LABOR_RATE_CENTS_PER_MIN


def final_alteration_cost_cents(actual_labor_minutes, refitting_count):
    """Actual variant: ceil(minutes * rate * (1 + 0.10 * refitting_count)).

    Ceiling applied ONCE to the final product. Use exact integer arithmetic:
    multiplier (1 + 0.10*n) = (10 + n) / 10.
    """
    base_actual = actual_labor_minutes * LABOR_RATE_CENTS_PER_MIN
    # refit_multiplier = 1 + (REFIT_SURCHARGE_PCT * refitting_count) = (10 + refitting_count)/10
    numerator = base_actual * (10 + refitting_count)
    return math.ceil(numerator / 10)


def min_deposit_cents(plan_total_cents):
    """Deposit floor: ceil(plan_total_cents * 0.50)."""
    return _ceil_pct(plan_total_cents, DEPOSIT_FLOOR_PCT)


def base_installment_cents(plan_total_cents, deposit_cents, term_installments):
    """Waterfall: floor(financed / term_installments); remainder loads final."""
    financed = plan_total_cents - deposit_cents
    return financed // term_installments


# Rush halves the standard lead time (deterministic; "rush shortens lead",
# PRD §3.3/§3.4). Kept >= 1 since standard_lead_days >= 1.
RUSH_LEAD_DIVISOR = 2


def effective_lead_days(standard_lead_days, is_rush):
    if not is_rush:
        return standard_lead_days
    return max(1, math.ceil(standard_lead_days / RUSH_LEAD_DIVISOR))
