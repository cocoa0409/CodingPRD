"""Withholding pipeline calculations.

Every output is integer cents, floor-divided per §2.8 / SCAFFOLD §1.3.
"""

# Calculation constants (SCAFFOLD §1.3)
PAY_PERIODS_PER_YEAR = 26
STANDARD_DEDUCTION_CENTS = {
    "SINGLE": 1_460_000,
    "MARRIED_JOINT": 2_920_000,
    "HEAD_OF_HOUSEHOLD": 2_190_000,
}
SS_WAGE_BASE_CENTS = 16_860_000
SS_RATE_BASIS_POINTS = 620
MEDICARE_RATE_BASIS_POINTS = 145
ADDL_MEDICARE_THRESHOLD_CENTS = 20_000_000
ADDL_MEDICARE_RATE_BASIS_POINTS = 90
CCPA_MAX_BASIS_POINTS_CREDITOR_ONLY = 2500
CCPA_MAX_BASIS_POINTS_WITH_CHILD_SUPPORT = 5000

STATE_JURISDICTIONS_WITH_NO_INCOME_TAX = {"STATE:TX", "STATE:WA"}


# -----------------------------------------------------------------------------
# gross_wages_calc
# -----------------------------------------------------------------------------

def gross_wages(pay_type, regular_hours_e2, overtime_hours_e2, double_hours_e2,
                retro_amount_cents, hourly_rate_cents):
    """SCAFFOLD §1.3 gross_wages_calc.

    All amounts in cents; hours fields scaled by 100 (e.g. 4000 = 40.00 hours).
    """
    if pay_type == "REGULAR":
        return (regular_hours_e2 * hourly_rate_cents) // 100
    if pay_type == "OVERTIME":
        # multiplier 1.5: hours * rate * 1.5 / 100 == hours * rate * 3 // 200
        return (overtime_hours_e2 * hourly_rate_cents * 3) // 200
    if pay_type == "DOUBLE":
        return (double_hours_e2 * hourly_rate_cents * 2) // 100
    if pay_type == "RETRO":
        return retro_amount_cents or 0
    return 0


# -----------------------------------------------------------------------------
# Bracket sum helper
# -----------------------------------------------------------------------------

def bracket_sum(amount_cents, brackets_json):
    """Floor-divide per bracket, then sum.

    brackets_json items: {"lower_cents", "upper_cents_or_null", "rate_basis_points"}
    A bracket contributes (min(amount, upper) - lower) * rate / 10000 if amount > lower.
    """
    if not brackets_json:
        return 0
    total = 0
    for b in brackets_json:
        lower = b.get("lower_cents", 0)
        upper = b.get("upper_cents_or_null")
        rate = b.get("rate_basis_points", 0)
        if amount_cents <= lower:
            continue
        effective_upper = amount_cents if upper is None else min(amount_cents, upper)
        slice_amount = effective_upper - lower
        if slice_amount <= 0:
            continue
        total += (slice_amount * rate) // 10000
    return total


# -----------------------------------------------------------------------------
# Federal withholding — provisional
# -----------------------------------------------------------------------------

def federal_withholding_provisional(gross_wages_cents, pay_type, w4, fed_table):
    """SCAFFOLD §1.3 federal_withholding_provisional.

    w4: dict with keys filing_status, dependents_amount_cents, other_income_cents,
        deductions_cents, extra_withholding_cents.
    fed_table: TaxRateTable dict for (jurisdiction=FEDERAL, year, filing_status), or
               None if missing (callers should handle missing-table elsewhere).
    """
    extra = (w4.get("extra_withholding_cents") or 0) if w4 else 0

    if pay_type in ("OVERTIME", "DOUBLE", "RETRO"):
        # Supplemental flat-rate path
        sup_bp = (fed_table.get("supplemental_flat_basis_points") or 0) if fed_table else 0
        supplemental_tax = (gross_wages_cents * sup_bp) // 10000
        per_pay_tax = supplemental_tax + extra
        return max(0, per_pay_tax)

    # REGULAR — percentage method
    if w4 is None:
        # Should never happen: ERR_NO_W4_ON_FILE guards at the route layer.
        return max(0, extra)

    filing_status = w4["filing_status"]
    annual_wages = gross_wages_cents * PAY_PERIODS_PER_YEAR
    adjusted_annual = (
        annual_wages
        + (w4.get("other_income_cents") or 0)
        - (w4.get("deductions_cents") or 0)
        - STANDARD_DEDUCTION_CENTS[filing_status]
    )
    if fed_table is None or not fed_table.get("brackets_json"):
        annual_tax = 0
    else:
        annual_tax = bracket_sum(adjusted_annual, fed_table["brackets_json"])
    per_pay_tax = annual_tax // PAY_PERIODS_PER_YEAR
    per_pay_tax -= (w4.get("dependents_amount_cents") or 0) // PAY_PERIODS_PER_YEAR
    per_pay_tax += extra
    return max(0, per_pay_tax)


def federal_withholding_reconciled(gross_wages_cents, pay_type, w4, fed_table,
                                   prior_ytd_wages, prior_ytd_fed_withheld):
    """SCAFFOLD §1.3 federal_withholding_reconciled (year-end true-up).

    Always uses the bracket path (no supplemental-flat shortcut), even for
    OVERTIME/DOUBLE/RETRO paychecks — the reconciled variant is the authoritative
    year-end calculation against actual YTD wages.
    """
    if w4 is None:
        # No filed W-4 means no bracket math possible — leave at zero.
        return 0
    filing_status = w4["filing_status"]
    annual_wages_actual = prior_ytd_wages + gross_wages_cents
    adjusted_annual = (
        annual_wages_actual
        + (w4.get("other_income_cents") or 0)
        - (w4.get("deductions_cents") or 0)
        - STANDARD_DEDUCTION_CENTS[filing_status]
    )
    if fed_table is None or not fed_table.get("brackets_json"):
        annual_tax_actual = 0
    else:
        annual_tax_actual = bracket_sum(adjusted_annual, fed_table["brackets_json"])
    annual_tax_actual -= (w4.get("dependents_amount_cents") or 0)
    annual_tax_actual += (w4.get("extra_withholding_cents") or 0) * PAY_PERIODS_PER_YEAR
    return max(0, annual_tax_actual - prior_ytd_fed_withheld)


# -----------------------------------------------------------------------------
# State / Local withholding
# -----------------------------------------------------------------------------

def state_or_local_withholding(gross_wages_cents, pay_type, table, jurisdiction):
    """SCAFFOLD §1.3 state_local_withholding for one jurisdiction.

    Returns 0 when the table is missing/empty or jurisdiction has no income tax.
    """
    if jurisdiction in STATE_JURISDICTIONS_WITH_NO_INCOME_TAX:
        return 0
    if table is None or not table.get("brackets_json"):
        return 0

    if pay_type == "REGULAR":
        per_pay_tax = bracket_sum(gross_wages_cents, table["brackets_json"])
    else:
        # OVERTIME / DOUBLE / RETRO — flat supplemental
        sup_bp = table.get("supplemental_flat_basis_points") or 0
        per_pay_tax = (gross_wages_cents * sup_bp) // 10000
    return max(0, per_pay_tax)


# -----------------------------------------------------------------------------
# Social Security (fica_ss)
# -----------------------------------------------------------------------------

def fica_ss(gross_wages_cents, employee_ytd_ss_wages):
    """SCAFFOLD §1.3 fica_ss_calc.

    Caps at SS_WAGE_BASE_CENTS YTD; returns ss_withheld_cents.
    """
    remaining_capacity = max(0, SS_WAGE_BASE_CENTS - employee_ytd_ss_wages)
    taxable = min(gross_wages_cents, remaining_capacity)
    return (taxable * SS_RATE_BASIS_POINTS) // 10000


def ytd_ss_increment(gross_wages_cents, employee_ytd_ss_wages):
    """Amount to add to ytd_ss_wages_cents on PAID transition; capped at base."""
    remaining_capacity = max(0, SS_WAGE_BASE_CENTS - employee_ytd_ss_wages)
    return min(gross_wages_cents, remaining_capacity)


# -----------------------------------------------------------------------------
# Medicare base + additional
# -----------------------------------------------------------------------------

def medicare_base(gross_wages_cents):
    return (gross_wages_cents * MEDICARE_RATE_BASIS_POINTS) // 10000


def medicare_additional(gross_wages_cents, prior_ytd_medicare_wages):
    """SCAFFOLD §1.3 medicare_addl_calc.

    Strictly above the threshold; rate 0.9% floor-divided.
    """
    prior_ytd = prior_ytd_medicare_wages
    new_ytd = prior_ytd + gross_wages_cents
    taxable_above = max(0, new_ytd - ADDL_MEDICARE_THRESHOLD_CENTS) - max(0, prior_ytd - ADDL_MEDICARE_THRESHOLD_CENTS)
    return (taxable_above * ADDL_MEDICARE_RATE_BASIS_POINTS) // 10000
