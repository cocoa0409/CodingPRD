"""Calculation rules (scaffold section 1.3 / PRD section 3).

All monetary quantities are integer cents; fractional intermediates resolve
with round-half-up (Decimal + ROUND_HALF_UP), never float arithmetic.
"""

from decimal import Decimal, ROUND_HALF_UP

# ---- core_credit_calculation ----
GRADE_MULT = {
    "GRADE_A": Decimal("1.00"),
    "GRADE_B": Decimal("0.60"),
    "GRADE_C": Decimal("0.30"),
    "REJECT": Decimal("0.00"),
}
PROVISIONAL_MULT = Decimal("1.00")
COMPONENT_DEDUCTION_CENTS = {
    "CRANKSHAFT": 40000,
    "CYLINDER_HEAD": 25005,
    "ENGINE_BLOCK": 50000,
    "CAMSHAFT": 33335,
}

# ---- deposit_refund_calculation (inclusive upper bounds) ----
BRACKET_1_MAX_DAYS = 30
BRACKET_1_PCT = Decimal("1.00")
BRACKET_2_MAX_DAYS = 60
BRACKET_2_PCT = Decimal("0.80")
BRACKET_3_MAX_DAYS = 90
BRACKET_3_PCT = Decimal("0.50")
FORFEIT_PCT = Decimal("0.00")

# ---- warranty_settlement_calculation ----
WARRANTY_MONTHS = 12
DAYS_PER_MONTH = 30
WARRANTY_DAYS = 360  # 12 months x 30 days


def _cents(value):
    """Round a Decimal to whole cents, half-up, returned as int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def provisional_credit_cents(spec):
    """Provisional variant: base credit assuming GRADE_A with nothing missing."""
    return _cents(Decimal(spec["core_base_credit_cents"]) * PROVISIONAL_MULT)


def final_credit_cents(spec, grade, missing_components):
    """Final variant.  Rounding order is pinned: the base component is rounded
    half-up once; each missing-component deduction line is rounded half-up to
    whole cents BEFORE the lines are summed; the total is then subtracted and
    the result floored at zero."""
    mult = GRADE_MULT[grade]
    base_component = _cents(Decimal(spec["core_base_credit_cents"]) * mult)
    total_deductions = 0
    for part in missing_components:
        total_deductions += _cents(Decimal(COMPONENT_DEDUCTION_CENTS[part]) * mult)
    return max(0, base_component - total_deductions)


def deposit_bracket_pct(age_days):
    if age_days <= BRACKET_1_MAX_DAYS:
        return BRACKET_1_PCT
    if age_days <= BRACKET_2_MAX_DAYS:
        return BRACKET_2_PCT
    if age_days <= BRACKET_3_MAX_DAYS:
        return BRACKET_3_PCT
    return FORFEIT_PCT


def deposit_refund(amount_cents, age_days):
    """Returns (bracket_pct, refunded_cents, forfeited_cents)."""
    pct = deposit_bracket_pct(age_days)
    refunded = _cents(Decimal(amount_cents) * pct)
    return pct, refunded, amount_cents - refunded


def sale_price_cents(spec, distributor):
    """round_half_up(list_price_cents * (1 - volume_discount_pct)); the deposit
    is never part of the price.  Warranty replacements bypass this rule (0)."""
    discount = Decimal(str(distributor["volume_discount_pct"]))
    return _cents(Decimal(spec["list_price_cents"]) * (Decimal(1) - discount))


def warranty_credit_cents(sale_price_cents_value, months_in_service, teardown_fee_cents):
    """Credit variant, pinned evaluation order: months used first (already on
    the claim), then remaining ratio floored at zero, then the prorated amount
    rounded half-up, then subtract the fee, then floor at zero."""
    remaining = max(0, WARRANTY_MONTHS - months_in_service)
    ratio = Decimal(remaining) / Decimal(WARRANTY_MONTHS)
    prorated = _cents(Decimal(sale_price_cents_value) * ratio)
    return max(0, prorated - teardown_fee_cents)
