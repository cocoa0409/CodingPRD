"""Calculation rules (SCAFFOLD section 1.3 / PRD sections 3.2, 3.5).

All money is integer cents. Percentages and scores are Decimal, rounded
half-up to exactly two decimal places. Reservations are rounded half-up to
whole cents per case BEFORE any summation (pinned rounding order).
"""
from decimal import Decimal, ROUND_HALF_UP

# poverty_percentage_screen constants
POVERTY_BASE_CENTS = 1506000            # $15,060.00 one-person FPL
POVERTY_PER_ADDITIONAL_CENTS = 538000   # +$5,380.00 per additional member
STANDARD_CAP_PCT = Decimal("125.00")

# priority_score constants
VULN_STEP = Decimal("0.15")
VULN_MULT_CAP = Decimal("1.75")
URGENCY_HIGH = Decimal(20)
URGENCY_MED = Decimal(10)
SCORE_CAP = Decimal("100.00")

# service level / caseload constants
EXTENDED_MIN_PRIORITY = Decimal("60.00")
EXTENDED_WEIGHT = 5
ADVICE_WEIGHT = 2

TWO_DP = Decimal("0.01")


def round2(d):
    return d.quantize(TWO_DP, rounding=ROUND_HALF_UP)


def fpl_cents(household_size):
    return POVERTY_BASE_CENTS + POVERTY_PER_ADDITIONAL_CENTS * (household_size - 1)


def poverty_pct(income_cents, household_size):
    """income_cents / fpl_cents * 100, rounded half-up to 2dp."""
    return round2(Decimal(income_cents) / Decimal(fpl_cents(household_size)) * Decimal(100))


def standard_screen_pass(gross_pct, receives_means_tested_benefits):
    """Benefits auto-pass, or gross percentage at most 125.00 (inclusive)."""
    return bool(receives_means_tested_benefits) or gross_pct <= STANDARD_CAP_PCT


def priority_score(base_weight, n_vulnerability_factors, case_type):
    mult = Decimal(1) + VULN_STEP * n_vulnerability_factors
    if mult > VULN_MULT_CAP:
        mult = VULN_MULT_CAP
    if case_type in ("EVICTION_DEFENSE", "FAMILY_DV"):
        urgency = URGENCY_HIGH
    elif case_type == "BENEFITS_APPEAL":
        urgency = URGENCY_MED
    else:
        urgency = Decimal(0)
    score = round2(Decimal(base_weight) * mult + urgency)
    return score if score <= SCORE_CAP else SCORE_CAP


def case_weight(service_level):
    return EXTENDED_WEIGHT if service_level == "EXTENDED" else ADVICE_WEIGHT


def reservation_cents(per_case_rate_cents, weight):
    """Per-case reservation: rate * weight / 5, rounded half-up to whole cents."""
    return int((Decimal(per_case_rate_cents) * Decimal(weight)
                / Decimal(EXTENDED_WEIGHT)).quantize(Decimal("1"),
                                                    rounding=ROUND_HALF_UP))


def utilization_pct(part, whole):
    if not whole:
        return 0.0
    return float(round2(Decimal(part) / Decimal(whole) * Decimal(100)))
