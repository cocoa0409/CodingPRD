"""Calculation rules (PRD 2.5, 3.4, 3.8, 3.5, 3.3, 3.10 / SCAFFOLD 1.3).
All monetary amounts are integer cents. The only rounding is the coinsurance
product, rounded half-up to whole cents."""
from decimal import Decimal, ROUND_HALF_UP

# coding_compliance_risk constants (SCAFFOLD 1.3)
W_UNSPECIFIED = 40
W_PER_SECONDARY = 10
SECONDARY_FREE_COUNT = 3
W_MISMATCH = 35
AUDIT_THRESHOLD = 50

BAD_DEBT_AGING_DAYS = 120


def round_half_up_cents(value):
    """Round a Decimal/number to a whole integer using ROUND_HALF_UP."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def estimate_patient_responsibility(expected_allowed, policy, accum):
    """Forward-looking estimate at eligibility verification (PRD 3.4).

    expected_allowed = encounter.total_charges_cents (current POSTED total).
    Uses accumulator state at check time as baseline.
    """
    deductible_cents = policy["deductible_cents"]
    coinsurance_pct = policy["coinsurance_pct"]
    oop_max_cents = policy["oop_max_cents"]
    deductible_met = accum["deductible_met_cents"]
    oop_met = accum["oop_met_cents"]

    remaining_deductible = max(0, deductible_cents - deductible_met)
    deductible_portion = min(expected_allowed, remaining_deductible)
    after_deductible = expected_allowed - deductible_portion
    coinsurance_portion = round_half_up_cents(
        Decimal(after_deductible) * Decimal(str(coinsurance_pct))
    )
    raw_patient = deductible_portion + coinsurance_portion
    remaining_oop = max(0, oop_max_cents - oop_met)
    return min(raw_patient, remaining_oop)


def final_patient_responsibility(allowed, policy, accum):
    """Final actual patient responsibility at adjudication (PRD 3.8).

    Returns (patient_responsibility_cents, deductible_applied). The caller
    advances the accumulator: deductible_met += deductible_applied and
    oop_met += patient_responsibility_cents (never past policy limits).
    """
    deductible_cents = policy["deductible_cents"]
    coinsurance_pct = policy["coinsurance_pct"]
    oop_max_cents = policy["oop_max_cents"]
    deductible_met = accum["deductible_met_cents"]
    oop_met = accum["oop_met_cents"]

    remaining_deductible = max(0, deductible_cents - deductible_met)
    deductible_applied = min(allowed, remaining_deductible)
    after_deductible = allowed - deductible_applied
    coinsurance_raw = round_half_up_cents(
        Decimal(after_deductible) * Decimal(str(coinsurance_pct))
    )
    remaining_oop = max(0, oop_max_cents - oop_met)
    raw_patient = deductible_applied + coinsurance_raw
    patient_responsibility = min(raw_patient, remaining_oop)
    return patient_responsibility, deductible_applied


def coding_compliance_risk(principal_icd10, secondary_icd10, distinct_charge_cpt_count):
    """Weighted coding-compliance risk (PRD 3.5). Factors summed in fixed order:
    unspecified principal, excess secondary codes, charge-to-code mismatch."""
    score = 0
    # factor 1: unspecified principal diagnosis (no decimal point OR ends in '.9')
    if "." not in principal_icd10 or principal_icd10.endswith(".9"):
        score += W_UNSPECIFIED
    # factor 2: excess secondary codes beyond the first three
    score += W_PER_SECONDARY * max(0, len(secondary_icd10) - SECONDARY_FREE_COUNT)
    # factor 3: charge-to-code mismatch
    if distinct_charge_cpt_count > (1 + len(secondary_icd10)):
        score += W_MISMATCH
    return score
