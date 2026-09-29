"""Pure calculation rules (PRD sections 3.1 - 3.9).

Every rounding operation is round half up and happens at exactly the decimal
place the PRD names; multi-step formulas keep every intermediate rounding.
"""

from decimal import Decimal, ROUND_HALF_UP

import constants as C

ZERO = Decimal("0")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return None
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up at `places` decimal places."""
    if value is None:
        return None
    quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    """Round half up to whole cents, as an int."""
    if value is None:
        return None
    return int(rhu(value, 0))


# --------------------------------------------------------------------------- #
# composite_viability_score
# --------------------------------------------------------------------------- #

def composite_viability_score(market, training, mission):
    total = (C.MARKET_WEIGHT * dec(market)
             + C.TRAINING_WEIGHT * dec(training)
             + C.MISSION_WEIGHT * dec(mission))
    return rhu(total, 2)


def viability_gate_met(line):
    if line["composite_viability_score"] < C.VIABILITY_COMPOSITE_FLOOR:
        return False
    weakest = min(line["market_viability_score"],
                  line["training_relevance_score"],
                  line["mission_alignment_score"])
    return weakest >= C.VIABILITY_DIMENSION_FLOOR


# --------------------------------------------------------------------------- #
# referral_eligibility_score
# --------------------------------------------------------------------------- #

def fpl_base_cents(household_size):
    if household_size <= 4:
        return C.FPL_ANNUAL_BASE_CENTS_BY_SIZE[household_size]
    return C.FPL_ANNUAL_BASE_CENTS_BY_SIZE[4] + (household_size - 4) * C.FPL_ADDITIONAL_PERSON_CENTS


def fpl_ratio(household_income_cents, household_size):
    base = fpl_base_cents(household_size)
    return rhu(dec(household_income_cents) * 12 / dec(base), 4)


def income_points(ratio):
    if ratio <= Decimal("1.0000"):
        return 35
    if ratio <= Decimal("1.5000"):
        return 25
    if ratio <= Decimal("2.0000"):
        return 15
    return 0


def eligibility_score(verified_barrier_codes, household_income_cents, household_size,
                      hours_available_per_week, mou_tier):
    distinct = len(set(verified_barrier_codes or []))
    barrier_points = min(C.BARRIER_CAP, distinct) * C.BARRIER_POINTS_EACH
    ratio = fpl_ratio(household_income_cents, household_size)
    points_income = income_points(ratio)
    availability_points = min(C.AVAILABILITY_CAP, int(hours_available_per_week) // 2)
    multiplier = C.PARTNER_MULTIPLIERS[mou_tier]
    total_points = barrier_points + points_income + availability_points
    score = rhu(dec(total_points) * multiplier, 2)
    return ratio, score


def priority_band(score):
    if score is None:
        return None
    if score >= C.BAND_A_FLOOR:
        return "BAND_A"
    if score >= C.BAND_B_FLOOR:
        return "BAND_B"
    return "BAND_C"


# --------------------------------------------------------------------------- #
# partner_conversion_rate / employer_retention_reliability
# --------------------------------------------------------------------------- #

def ratio_or_none(numerator, denominator, places=4):
    if denominator == 0:
        return None
    return rhu(dec(numerator) / dec(denominator), places)


# --------------------------------------------------------------------------- #
# shift labour cost
# --------------------------------------------------------------------------- #

def duration_hours(starts_at, ends_at):
    seconds = dec((ends_at - starts_at).total_seconds())
    return rhu(seconds / dec(3600), 3)


def wage_cost_cents(actual_hours, wage_cents_per_hour):
    return rhu_cents(dec(actual_hours) * dec(wage_cents_per_hour))


# --------------------------------------------------------------------------- #
# subsidy allocation, true cost and subsidy draw
# --------------------------------------------------------------------------- #

def mission_share_hours(trainee_hours, supervisor_hours):
    denominator = dec(trainee_hours) + dec(supervisor_hours)
    if denominator == 0:
        return Decimal("0.0000")
    return rhu(dec(trainee_hours) / denominator, 4)


def mission_share_revenue(revenue_cents, gross_cost_cents):
    if gross_cost_cents == 0:
        return Decimal("0.0000")
    raw = Decimal(1) - (dec(revenue_cents or 0) / dec(gross_cost_cents))
    if raw < 0:
        raw = ZERO
    return rhu(raw, 4)


def allocate_entry(amount_cents, classification, mission_share):
    if classification == "MISSION":
        return amount_cents, 0
    if classification == "BUSINESS":
        return 0, amount_cents
    mission = rhu_cents(dec(amount_cents) * dec(mission_share))
    return mission, amount_cents - mission


def per_trainee_hour(amount_cents, trainee_hours):
    if trainee_hours is None or dec(trainee_hours) == 0:
        return None
    return rhu(dec(amount_cents) / dec(trainee_hours), 2)


def margin_pct(revenue_cents, business_operating_cost_cents):
    if revenue_cents == 0:
        return Decimal("-1.0000")
    return rhu((dec(revenue_cents) - dec(business_operating_cost_cents)) / dec(revenue_cents), 4)


def subsidy_rate(margin):
    if margin >= C.SUBSIDY_TIER_HIGH_MARGIN:
        return C.SUBSIDY_RATE_HIGH_MARGIN
    if margin >= C.SUBSIDY_TIER_LOW_MARGIN:
        return C.SUBSIDY_RATE_MID_MARGIN
    return C.SUBSIDY_RATE_LOW_MARGIN


def subsidy_draw_cents(mission_cost_cents, rate):
    return rhu_cents(dec(mission_cost_cents) * dec(rate))


# --------------------------------------------------------------------------- #
# wage progression
# --------------------------------------------------------------------------- #

def wage_progression_pct(verified_wage, graduation_wage):
    if graduation_wage in (None, 0) or verified_wage is None:
        return None
    return rhu((dec(verified_wage) - dec(graduation_wage)) / dec(graduation_wage), 4)


def wage_progression_floor_cents(graduation_wage):
    return rhu_cents(dec(graduation_wage) * C.WAGE_PROGRESSION_FLOOR)


# --------------------------------------------------------------------------- #
# retention
# --------------------------------------------------------------------------- #

def whole_days_between(start, end):
    return int((end - start).total_seconds() // 86400)


def retention_outcome_for(days_after_hire):
    if days_after_hire < C.EARLY_SEPARATION_DAYS:
        return "FAILED_EARLY"
    if days_after_hire < C.LATE_SEPARATION_DAYS:
        return "FAILED_LATE"
    return "RETAINED_180"
