"""Monetary calculations. All money is integer cents; round-half-up where a rate
multiplication occurs, exactly as PRD section 2.7 and section 3.5/3.9 specify."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round a Decimal/number to the nearest whole cent, halves up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- estimated_assignment_cost (at booking) --------------------------------
def estimated_assignment_cost(daily_rate_cents, union_code, fringe):
    """base = daily_rate_cents; projected fringe only if union in {SAG,IATSE,DGA}
    AND a matching UnionFringe row exists; round the rate term then add the flat."""
    base = daily_rate_cents
    if union_code in ("SAG_AFTRA", "IATSE", "DGA") and fringe is not None:
        proj_fringe = round_half_up(base * fringe["fringe_rate_bps"] / Decimal(10000))
        proj_fringe += fringe["pension_health_flat_cents"]
    else:
        proj_fringe = 0
    return base + proj_fringe


# --- union_fringe_accrual (at check-out) -----------------------------------
def union_fringe_accrual(daily_rate_cents, union_code, fringe):
    if union_code in ("SAG_AFTRA", "IATSE", "DGA") and fringe is not None:
        straight = daily_rate_cents
        f = round_half_up(straight * fringe["fringe_rate_bps"] / Decimal(10000))
        f += fringe["pension_health_flat_cents"]
        return f
    return 0


# --- meal_penalty (at check-out) -------------------------------------------
MEAL_INTERVAL_HOURS = 6.0
MEAL_FIRST_CENTS = 2500
MEAL_NEXT_CENTS = 3500


def meal_penalty(hours_worked, meal_breaks_taken, is_sag_aftra):
    """Only SAG-AFTRA crew accrue. required = floor(hours/6); missed = required -
    taken (>=0). Boundary inclusive: hours_worked >= 6.0 -> first required meal."""
    if not is_sag_aftra:
        return 0
    required_meals = int(hours_worked // MEAL_INTERVAL_HOURS)
    missed = max(0, required_meals - meal_breaks_taken)
    if missed <= 0:
        return 0
    return MEAL_FIRST_CENTS + (missed - 1) * MEAL_NEXT_CENTS


# --- turnaround_penalty (at check-out) -------------------------------------
MIN_TURNAROUND_HOURS = 10.0


def turnaround_penalty(rest_hours, has_prior, is_sag_aftra, daily_rate_cents):
    """Zero if no prior wrapped assignment or non-SAG. Else flat one day rate when
    rest_hours < 10.0 (>= 10.0 compliant -> 0)."""
    if not has_prior or not is_sag_aftra:
        return 0
    if rest_hours >= MIN_TURNAROUND_HOURS:
        return 0
    return daily_rate_cents


# --- actual_assignment_cost (at approve-pay) -------------------------------
STANDARD_DAY_HOURS = 12.0
OVERTIME_MULTIPLIER = 1.5


def actual_assignment_cost(daily_rate_cents, hours_worked, meal_penalty_cents,
                           turnaround_penalty_cents, fringe_cents):
    straight_time = daily_rate_cents
    hourly = Decimal(daily_rate_cents) / Decimal("12.0")
    ot_hours = max(0.0, hours_worked - STANDARD_DAY_HOURS)
    # overtime = hourly * 1.5 * ot_hours, rounded once as a single term.
    overtime = round_half_up(hourly * Decimal("1.5") * Decimal(str(ot_hours)))
    return (straight_time + overtime + meal_penalty_cents +
            turnaround_penalty_cents + fringe_cents)


# --- residual_accrual (marginal tier schedule on cumulative gross) ---------
TIER1_CAP_CENTS = 100000000
TIER2_CAP_CENTS = 500000000
TIER1_BPS = 120
TIER2_BPS = 180
TIER3_BPS = 240


def tier_residual(cumulative_cents):
    """Marginal-rate schedule applied to a cumulative total.
      tier 1: first 100,000,000 @ 120 bps
      tier 2: next 400,000,000 (100M..500M) @ 180 bps
      tier 3: above 500,000,000 @ 240 bps
    Computed over the cumulative total as a whole, summed per tier (no per-event
    rounding); the difference of two such totals gives a single event's residual."""
    x = cumulative_cents
    total = Decimal(0)
    tier1 = min(x, TIER1_CAP_CENTS)
    total += Decimal(tier1) * TIER1_BPS / Decimal(10000)
    if x > TIER1_CAP_CENTS:
        tier2 = min(x, TIER2_CAP_CENTS) - TIER1_CAP_CENTS
        total += Decimal(tier2) * TIER2_BPS / Decimal(10000)
    if x > TIER2_CAP_CENTS:
        tier3 = x - TIER2_CAP_CENTS
        total += Decimal(tier3) * TIER3_BPS / Decimal(10000)
    return total


def residual_amount(prior_cumulative, new_cumulative):
    """Marginal residual produced by moving cumulative from prior to new.
    tier_residual computed once per total then differenced, rounded half-up."""
    marginal = tier_residual(new_cumulative) - tier_residual(prior_cumulative)
    return round_half_up(marginal)
