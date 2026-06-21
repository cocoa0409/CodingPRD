"""Calculation rules (SCAFFOLD §3, PRD §3) — all money in integer cents,
round_half_up, no floats for money. GPA compared at 2 decimal places."""

from decimal import Decimal, ROUND_HALF_UP

# ---- Constants ----
# rubric_weighted_value weights
W_ACADEMIC = Decimal("0.5")
W_NEED = Decimal("0.3")
W_ESSAY = Decimal("0.2")

# provisional_award score tiers
AWARD_SCORE_FLOOR = Decimal("60")
TIER_HIGH = Decimal("90")
TIER_MID = Decimal("75")
MULT_HIGH = Decimal("1.00")
MULT_MID = Decimal("0.80")
MULT_LOW = Decimal("0.60")

# final_award GPA factors
GPA_HIGH = Decimal("3.50")
GPA_MID = Decimal("3.00")
FACTOR_HIGH = Decimal("1.00")
FACTOR_MID = Decimal("0.90")
FACTOR_LOW = Decimal("0.80")

SCORING_QUORUM = 2
MAX_REVISION_ROUNDS = 2
MAX_CONCURRENT_ASSIGNMENTS = 3
AWARD_SCORE_FLOOR_INT = 60


def _round2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _round_cents(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _gpa(value):
    """Normalize a GPA to 2 decimal places for comparison."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def rubric_weighted_value(academic_score, need_score, essay_score):
    """weighted_value rounded half up to 2 decimals; returned as float for JSON."""
    total = (Decimal(academic_score) * W_ACADEMIC
             + Decimal(need_score) * W_NEED
             + Decimal(essay_score) * W_ESSAY)
    return float(_round2(total))


def rubric_total(weighted_values):
    """Mean of the submitted weighted_values: sum, divide, then a single final
    round half up to 2 decimals. Divisor guaranteed non-zero by quorum."""
    total = sum((Decimal(str(v)) for v in weighted_values), Decimal("0"))
    quotient = total / Decimal(len(weighted_values))
    return float(_round2(quotient))


def eligibility(verified_gpa, residency_state, field_of_study, crit):
    """Returns (matched, failures[]). Failures appended in fixed order
    [GPA, RESIDENCY, FIELD]. GPA comparison inclusive at boundary, 2 decimals."""
    failures = []
    gpa_ok = _gpa(verified_gpa) >= _gpa(crit["min_gpa"])
    if not gpa_ok:
        failures.append("GPA")
    residency_ok = (crit["required_residency_state"] == "ANY"
                    or residency_state == crit["required_residency_state"])
    if not residency_ok:
        failures.append("RESIDENCY")
    field_ok = (crit["required_field_of_study"] == "ANY"
                or field_of_study == crit["required_field_of_study"])
    if not field_ok:
        failures.append("FIELD")
    return (len(failures) == 0), failures


def provisional_award(requested_amount_cents, rubric_total_value, max_award_cents):
    """Forward-looking: score-tier multiplier on requested amount, rounded half up,
    then capped at max_award_cents."""
    rt = Decimal(str(rubric_total_value))
    if rt >= TIER_HIGH:
        mult = MULT_HIGH
    elif rt >= TIER_MID:
        mult = MULT_MID
    else:
        mult = MULT_LOW  # rt in [AWARD_SCORE_FLOOR, TIER_MID)
    raw = _round_cents(Decimal(requested_amount_cents) * mult)
    return min(raw, max_award_cents)


def final_award(provisional_award_cents, verified_gpa, max_award_cents):
    """Chronological: verified-GPA factor on the committed provisional amount,
    rounded half up, then capped at max_award_cents."""
    gpa = _gpa(verified_gpa)
    if gpa >= GPA_HIGH:
        factor = FACTOR_HIGH
    elif gpa >= GPA_MID:
        factor = FACTOR_MID
    else:
        factor = FACTOR_LOW
    raw = _round_cents(Decimal(provisional_award_cents) * factor)
    return min(raw, max_award_cents)


def meets_floor(reported_gpa, renewal_gpa_floor):
    """Inclusive GPA comparison at 2 decimals."""
    return _gpa(reported_gpa) >= _gpa(renewal_gpa_floor)


def score_clears_floor(rubric_total_value):
    return Decimal(str(rubric_total_value)) >= AWARD_SCORE_FLOOR
