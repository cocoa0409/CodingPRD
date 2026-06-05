"""Calculation rules (SCAFFOLD §1.3, PRD §2.6 / §3).

All money is integer cents. round_half_up is applied once per multiply step in
a pinned order (round-per-step, never round-at-end).
"""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(numerator, denominator):
    """Integer round-half-up of numerator/denominator."""
    return int((Decimal(numerator) / Decimal(denominator)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- compute_premium ------------------------------------------------------

TOBACCO_MULT_MILLI = 1500
NON_TOBACCO_MULT_MILLI = 1000
PROVISIONAL_CLASS_MULT_MILLI = 1000
PREFERRED_CLASS_MULT_MILLI = 850
STANDARD_CLASS_MULT_MILLI = 1000
TABLE_STEP_MILLI = 250


def class_mult_milli_for(risk_class, table_rating):
    if risk_class == "PREFERRED":
        return PREFERRED_CLASS_MULT_MILLI
    if risk_class == "STANDARD":
        return STANDARD_CLASS_MULT_MILLI
    # TABLE_N -> 1000 + N * 250
    return STANDARD_CLASS_MULT_MILLI + table_rating * TABLE_STEP_MILLI


def compute_premium(requested_face_amount_cents, base_annual_rate_per_thousand_cents,
                    tobacco_use, class_mult_milli):
    """Pinned-order premium computation, round-per-step.

    step 1: thousands = face // 100000  (integer division)
    step 2: base = base_rate * thousands
    step 3: tobacco_mult = 1500 if tobacco else 1000 (milli)
    step 4: class_mult (caller-supplied, milli)
    step 5: after_tobacco = round_half_up(base * tobacco_mult / 1000)
            premium       = round_half_up(after_tobacco * class_mult / 1000)
    """
    thousands = requested_face_amount_cents // 100000
    base = base_annual_rate_per_thousand_cents * thousands
    tobacco_mult = TOBACCO_MULT_MILLI if tobacco_use else NON_TOBACCO_MULT_MILLI
    after_tobacco = round_half_up(base * tobacco_mult, 1000)
    premium = round_half_up(after_tobacco * class_mult_milli, 1000)
    return premium


# ---- classify_risk --------------------------------------------------------

BMI_BAND_1_MAX = Decimal("27.5")
BMI_BAND_2_MAX = Decimal("32.0")
BMI_BAND_3_MAX = Decimal("37.0")
BP_BAND_1_MAX = 135
BP_BAND_2_MAX = 150
TOBACCO_DEBITS = 50
MIB_FLAGGED_DEBITS = 75
TABLE_STEP_DEBITS = 50
TABLE_CAP = 8


def compute_bmi(weight_pounds, height_inches):
    """BMI to 3 decimals via integer milli-arithmetic.

    bmi = round_half_up(weight * 703000 / (height^2)) / 1000
    """
    milli = round_half_up(weight_pounds * 703000, height_inches * height_inches)
    return Decimal(milli) / Decimal(1000)


def bmi_band_debits(bmi):
    if bmi <= BMI_BAND_1_MAX:
        return 0
    if bmi <= BMI_BAND_2_MAX:
        return 50
    if bmi <= BMI_BAND_3_MAX:
        return 100
    return 200


def bp_band_debits(systolic_bp):
    if systolic_bp <= BP_BAND_1_MAX:
        return 0
    if systolic_bp <= BP_BAND_2_MAX:
        return 50
    return 100


def classify_risk(weight_pounds, height_inches, systolic_bp, tobacco_use, any_mib_flagged):
    """Returns (build_debits, total_debits, risk_class, table_rating)."""
    bmi = compute_bmi(weight_pounds, height_inches)
    build = bmi_band_debits(bmi) + bp_band_debits(systolic_bp)
    impairment = 0
    if tobacco_use:
        impairment += TOBACCO_DEBITS
    if any_mib_flagged:
        impairment += MIB_FLAGGED_DEBITS
    total = build + impairment

    # threshold, lower-bound inclusive
    if total < 50:
        return build, total, "PREFERRED", 0
    if total < 100:
        return build, total, "STANDARD", 0
    n = (total - 100) // TABLE_STEP_DEBITS + 1
    if n > TABLE_CAP:
        n = TABLE_CAP
    return build, total, f"TABLE_{n}", n


# ---- accrue_cash_value ----------------------------------------------------

BPS_DENOMINATOR = 10000


def accrual_increment(cumulative_premium_paid_cents, cash_value_accrual_rate_bps):
    return round_half_up(cumulative_premium_paid_cents * cash_value_accrual_rate_bps, BPS_DENOMINATOR)


# ---- available_loan_value -------------------------------------------------

def available_loan_value(gross_cash_value_cents, outstanding_loan_principal_cents,
                         max_loan_to_cash_value_pct):
    cap = round_half_up(gross_cash_value_cents * max_loan_to_cash_value_pct, 100)
    return max(0, cap - outstanding_loan_principal_cents)


# ---- interval overlap helpers ---------------------------------------------

def intervals_overlap(a_start, a_end, b_start, b_end):
    """True iff [a_start, a_end) and [b_start, b_end) overlap.

    Overlap iff a_start < b_end AND b_start < a_end. Touching endpoints
    (a_end == b_start) do NOT overlap (adjacency allowed).
    """
    return a_start < b_end and b_start < a_end
