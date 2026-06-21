"""Calculation rules (PRD §3 / SCAFFOLD §1.3).

All monetary work is in integer cents; the only rounding that occurs is in the
compensation sweep (gross*rate product, round-half-up). Match score rounds to
4 decimal places round-half-up after a clamp to 1.0.
"""
from decimal import Decimal, ROUND_HALF_UP

# match_score weights (SCAFFOLD calc match_score constants).
INCLUSION_WEIGHT = Decimal("0.6")
EXCLUSION_WEIGHT = Decimal("0.4")

# visit_compensation constants (SCAFFOLD calc visit_compensation constants).
BASE_VISIT_CENTS = 7500
ON_TIME_MINUTES = 15
LATE_GRACE_MINUTES = 60
ON_TIME_BONUS_CENTS = 2500
LATE_BONUS_CENTS = 1000
MILEAGE_RATE_CENTS = 1200

# compensation_sweep constants (SCAFFOLD calc compensation_sweep constants).
WITHHOLDING_THRESHOLD_CENTS = 30000
LOW_WITHHOLDING_RATE = Decimal("0.0")
HIGH_WITHHOLDING_RATE = Decimal("0.10")


def _attr_value(participant, attribute):
    """Left-hand value for a criterion predicate (PRD §3.3).

    biomarker_positive reads as 1.0 (true) / 0.0 (false); everything else is the
    participant's stored numeric value.
    """
    if attribute == "biomarker_positive":
        return 1.0 if participant.get("biomarker_positive") else 0.0
    return participant.get(attribute)


def predicate_holds(participant, criterion):
    """Whether the criterion's comparison holds for the participant (PRD §3.3)."""
    lhs = _attr_value(participant, criterion["attribute"])
    rhs = criterion["threshold"]
    comparator = criterion["comparator"]
    if comparator == "GE":
        return lhs >= rhs
    if comparator == "GT":
        return lhs > rhs
    if comparator == "LE":
        return lhs <= rhs
    if comparator == "LT":
        return lhs < rhs
    if comparator == "EQ":
        return lhs == rhs
    return False


def eligibility_match(criteria, participant):
    """Return (match_result, failed_criteria_count) (PRD §3.3 eligibility match).

    An INCLUSION criterion fails when its predicate does NOT hold; an EXCLUSION
    criterion fails when its predicate DOES hold.
    """
    failed = 0
    for c in criteria:
        holds = predicate_holds(participant, c)
        if c["kind"] == "INCLUSION" and not holds:
            failed += 1
        elif c["kind"] == "EXCLUSION" and holds:
            failed += 1
    result = "ELIGIBLE" if failed == 0 else "INELIGIBLE"
    return result, failed


def match_score(criteria, participant):
    """Weighted match score in [0,1] rounded to 4 dp round-half-up (PRD §3.3).

    The min(1.0, .) clamp is applied BEFORE rounding.
    """
    inclusion = [c for c in criteria if c["kind"] == "INCLUSION"]
    exclusion = [c for c in criteria if c["kind"] == "EXCLUSION"]
    if not inclusion and not exclusion:
        return 1.0

    inc_passed = sum(1 for c in inclusion if predicate_holds(participant, c))
    exc_clear = sum(1 for c in exclusion if not predicate_holds(participant, c))

    if inclusion and exclusion:
        raw = (INCLUSION_WEIGHT * (Decimal(inc_passed) / Decimal(len(inclusion)))
               + EXCLUSION_WEIGHT * (Decimal(exc_clear) / Decimal(len(exclusion))))
    elif inclusion:
        raw = Decimal(inc_passed) / Decimal(len(inclusion))
    else:
        raw = Decimal(exc_clear) / Decimal(len(exclusion))

    clamped = min(Decimal("1.0"), raw)
    rounded = clamped.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(rounded)


def visit_compensation(deviation_minutes, sequence_index):
    """payable_amount_cents for a completed visit (PRD §3.6). Exact integer cents."""
    base = BASE_VISIT_CENTS
    if deviation_minutes <= ON_TIME_MINUTES:
        bonus = ON_TIME_BONUS_CENTS
    elif deviation_minutes <= LATE_GRACE_MINUTES:
        bonus = LATE_BONUS_CENTS
    else:
        bonus = 0
    mileage = MILEAGE_RATE_CENTS * max(0, sequence_index - 1)
    return base + bonus + mileage


def compensation_sweep(gross_cents, enrollment_status):
    """Return net amount_cents after withholding (PRD §3.7).

    Order: gross -> tier -> withholding(round-half-up on gross*rate) -> net.
    For a WITHDRAWN enrollment the rate is forced to LOW (0.0) regardless of
    gross (early_termination_sweep variant).
    """
    if enrollment_status == "WITHDRAWN":
        rate = LOW_WITHHOLDING_RATE
    elif gross_cents >= WITHHOLDING_THRESHOLD_CENTS:
        rate = HIGH_WITHHOLDING_RATE
    else:
        rate = LOW_WITHHOLDING_RATE

    withholding = int((Decimal(gross_cents) * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return gross_cents - withholding
