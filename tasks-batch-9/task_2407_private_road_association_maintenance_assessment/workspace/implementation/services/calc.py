"""Pure calculation rules. All money is integer cents; all intermediate
quantities are exact rationals (fractions.Fraction) — never floats."""

import math
from fractions import Fraction

from db import to_fraction
from services import constants as C


# ---------------------------------------------------------------------------
# rounding
# ---------------------------------------------------------------------------

def round_half_up(value):
    """Round an exact rational to whole cents, halves away upward."""
    frac = to_fraction(value)
    numerator, denominator = frac.numerator, frac.denominator
    return (2 * numerator + denominator) // (2 * denominator)


def ratio_4dp(numerator, denominator):
    """Display-only ratio rounded half up to four decimal places."""
    if denominator == 0:
        return 0.0
    scaled = round_half_up(Fraction(numerator, denominator) * 10000)
    return float(Fraction(scaled, 10000))


# ---------------------------------------------------------------------------
# calculations.parcel_share_units
# ---------------------------------------------------------------------------

def frontage_share_units(frontage_feet, usage_class):
    return to_fraction(frontage_feet) * C.USAGE_MULTIPLIER[usage_class]


def trip_share_units(trips_per_day, frontage_feet):
    return (to_fraction(trips_per_day) * C.TRIP_UNIT_FACTOR
            + to_fraction(frontage_feet) * C.FRONTAGE_FLOOR_WEIGHT)


def parcel_units(parcel):
    parcel["frontage_share_units"] = frontage_share_units(
        parcel["frontage_feet"], parcel["usage_class"])
    parcel["trip_share_units"] = trip_share_units(
        parcel["trips_per_day"], parcel["frontage_feet"])


# ---------------------------------------------------------------------------
# calculations.annual_assessment_allocation / special_assessment_allocation
# ---------------------------------------------------------------------------

def allocate(budget_cents, units):
    """The pinned eight-step waterfall allocation.

    `units` is an ordered list of exact-rational share units. Returns
    (amounts, total_share_units, total_levied_cents, unallocated_residual_cents).
    A zero total of share units yields (None, 0, 0, 0) and the caller decides.
    """
    total_units = sum(units, Fraction(0))
    if total_units == 0:
        return None, Fraction(0), 0, 0

    budget = Fraction(budget_cents)
    cap = int(C.MAX_SINGLE_PARCEL_SHARE_PCT * budget_cents)  # floor
    floor_cents = C.MIN_CHARGE_CENTS

    clamped_values = []
    is_clamped = []
    for unit in units:
        raw = budget * unit / total_units
        value = min(max(raw, Fraction(floor_cents)), Fraction(cap))
        clamped_values.append(value)
        is_clamped.append(value != raw)

    residual = budget - sum(clamped_values, Fraction(0))
    unclamped_units = sum(
        (unit for unit, clamped in zip(units, is_clamped) if not clamped),
        Fraction(0),
    )

    finals = []
    for index, unit in enumerate(units):
        base = clamped_values[index]
        if not is_clamped[index] and unclamped_units > 0:
            want = residual * unit / unclamped_units
            if residual >= 0:
                adjustment = min(want, Fraction(cap) - base)
            else:
                adjustment = max(want, Fraction(floor_cents) - base)
            finals.append(base + adjustment)
        else:
            finals.append(base)

    amounts = [round_half_up(value) for value in finals]
    total_levied = sum(amounts)
    return amounts, total_units, total_levied, budget_cents - total_levied


# ---------------------------------------------------------------------------
# calculations.vote_threshold_resolution
# ---------------------------------------------------------------------------

def vote_threshold_bps(project_type, estimated_cost_cents, reserve_posture):
    base = C.BASE_THRESHOLD_BPS[project_type]
    cost_bump = C.THRESHOLD_BUMP_BPS if estimated_cost_cents > C.ESCALATION_COST_CENTS else 0
    posture_bump = C.THRESHOLD_BUMP_BPS if reserve_posture == "UNDERFUNDED" else 0
    return min(base + cost_bump + posture_bump, C.MAX_THRESHOLD_BPS)


# ---------------------------------------------------------------------------
# calculations.emergency_access_grade_evaluation
# ---------------------------------------------------------------------------

def required_turnouts(length_feet):
    quotient = to_fraction(length_feet) / C.TURNOUT_SPACING_FEET
    return max(0, int(math.ceil(quotient)) - 1)


def evaluate_access_grade(segment):
    compliant = (
        to_fraction(segment["width_feet"]) >= C.MIN_WIDTH_FEET
        and to_fraction(segment["max_grade_pct"]) <= C.MAX_GRADE_PCT
        and segment["turnaround_present"] is True
        and int(segment["turnout_count"]) >= int(segment["required_turnouts"])
        and (
            segment["bridge_present"] is False
            or (segment["bridge_load_rating_tons"] is not None
                and to_fraction(segment["bridge_load_rating_tons"]) >= C.MIN_BRIDGE_RATING_TONS)
        )
    )
    return "COMPLIANT" if compliant else "DEFICIENT"


# ---------------------------------------------------------------------------
# calculations.connection_fee
# ---------------------------------------------------------------------------

def connection_fee(frontage_feet, requested_usage_class, requested_trips_per_day,
                   deficit_cents, association_total_units):
    """Four components, each rounded half up on its own before summation."""
    new_units = frontage_share_units(frontage_feet, requested_usage_class)
    c_base = round_half_up(C.CONNECT_BASE_CENTS)
    c_frontage = round_half_up(to_fraction(frontage_feet) * C.CONNECT_FRONTAGE_RATE_CENTS_PER_FOOT)
    c_trips = round_half_up(to_fraction(requested_trips_per_day) * C.CONNECT_TRIP_RATE_CENTS)
    if association_total_units > 0:
        c_reserve = round_half_up(
            C.RESERVE_BUYIN_PCT * Fraction(deficit_cents) * new_units / association_total_units)
    else:
        c_reserve = 0
    return c_base + c_frontage + c_trips + c_reserve, c_reserve


# ---------------------------------------------------------------------------
# calculations.lien_payoff_amount
# ---------------------------------------------------------------------------

def lien_payoff(principal_cents, days_delinquent, interest_basis):
    principal = Fraction(principal_cents)
    if interest_basis == "STATUTORY":
        interest = principal * C.STATUTORY_ANNUAL_RATE * Fraction(days_delinquent) / Fraction(365)
        return principal_cents + round_half_up(interest)
    whole_months = days_delinquent // 30 if days_delinquent >= 0 else 0
    base = principal + Fraction(C.LIEN_FILING_COST_CENTS)
    growth = (Fraction(1) + C.POLICY_MONTHLY_RATE) ** whole_months
    return round_half_up(base * growth)


# ---------------------------------------------------------------------------
# calculations.project_reserve_draw
# ---------------------------------------------------------------------------

def project_reserve_draw(category, bid_amount_cents, proposal_funding_cents):
    if category in C.OPERATING_CATEGORIES:
        return 0
    return max(0, bid_amount_cents - proposal_funding_cents)


# ---------------------------------------------------------------------------
# calculations.reserve_balance_reconciliation (posture half)
# ---------------------------------------------------------------------------

def reserve_posture(balance_cents, target_cents):
    if balance_cents >= target_cents:
        return "FULLY_FUNDED"
    if balance_cents * 100 >= target_cents * C.ADEQUATE_RATIO_PCT:
        return "ADEQUATE"
    return "UNDERFUNDED"
