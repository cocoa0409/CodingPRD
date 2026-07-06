"""Calculation rules (PRD Section 2.7 and Section 3).

All monetary amounts are integer cents. Fractional-cent results are rounded
half up to whole cents. Energy savings are kWh rounded half up to one decimal
place. Pass/fail ratios are compared at full float precision.
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 50

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SAVINGS_PER_CFM50_KWH = Decimal("1.5")

# rebate_amount (PRD 3.7)
RATE_TABLE = {
    "ATTIC_INSULATION": {"TIER1": 50, "TIER2": 90, "TIER3": 130},
    "WALL_INSULATION": {"TIER1": 40, "TIER2": 70, "TIER3": 100},
    "CRAWL_INSULATION": {"TIER1": 30, "TIER2": 55, "TIER3": 80},
    "AIR_SEALING": {"FLAT": 25},
    "DUCT_SEALING": {"FLAT": 20},
}
MEASURE_CAP_CENTS = 200000

# tax_credit_25c (PRD 3.6)
CREDIT_RATE = Decimal("0.30")
ANNUAL_CAP_CENTS = 120000
QUALIFYING_25C_CATEGORIES = {
    "ATTIC_INSULATION",
    "WALL_INSULATION",
    "CRAWL_INSULATION",
    "AIR_SEALING",
}

# wap_income_eligibility (PRD 3.1)
FPL_MULTIPLIER = 2
FPL_SIZE1_CENTS = 1500000
FPL_PER_PERSON_CENTS = 500000

# cfm50_reduction (PRD 3.8)
MIN_REDUCTION_PCT = 0.20

# crew dwelling window buffer (PRD 3.5)
BUFFER_DAYS = 2


# ---------------------------------------------------------------------------
# Rounding helpers
# ---------------------------------------------------------------------------
def round_cents(value):
    """Round a numeric value half up to a whole number of integer cents."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_kwh(value):
    """Round a kWh figure half up to one decimal place, returned as float."""
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# wap_income_eligibility
# ---------------------------------------------------------------------------
def wap_income_limit_cents(household_size):
    return FPL_MULTIPLIER * (
        FPL_SIZE1_CENTS + (household_size - 1) * FPL_PER_PERSON_CENTS
    )


def wap_status(annual_gross_income_cents, income_limit_cents):
    # Boundary inclusive: income exactly equal to the limit is ELIGIBLE.
    return "ELIGIBLE" if annual_gross_income_cents <= income_limit_cents else "INELIGIBLE"


# ---------------------------------------------------------------------------
# rebate_amount (PROVISIONAL from target_r_value / FINALIZED from achieved_r_value)
# ---------------------------------------------------------------------------
def _tier(r_value):
    if r_value < 30:
        return "TIER1"
    if r_value < 49:
        return "TIER2"
    return "TIER3"


def rebate_amount(category, r_value, area_sqft):
    rates = RATE_TABLE[category]
    if "FLAT" in rates:
        rate = rates["FLAT"]
    else:
        rate = rates[_tier(r_value)]
    raw = Decimal(str(rate)) * Decimal(str(area_sqft))
    rounded = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return min(rounded, MEASURE_CAP_CENTS)


# ---------------------------------------------------------------------------
# tax_credit_25c (round EACH line to whole dollars first, THEN sum, THEN cap)
# ---------------------------------------------------------------------------
def tax_credit_25c(scope_items):
    total = 0
    for s in scope_items:
        if s["status"] not in ("INSTALLED", "VERIFIED"):
            continue
        if s["category"] not in QUALIFYING_25C_CATEGORIES:
            continue
        actual = s.get("actual_cost_cents") or 0
        line_dollars = (CREDIT_RATE * Decimal(actual) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        total += int(line_dollars) * 100
    return min(total, ANNUAL_CAP_CENTS)


# ---------------------------------------------------------------------------
# cfm50_reduction
# ---------------------------------------------------------------------------
def cfm50_reduction(baseline_cfm50, post_cfm50):
    """Return the reduction fraction at full float precision."""
    return (baseline_cfm50 - post_cfm50) / baseline_cfm50


def verified_savings_kwh(baseline_cfm50, post_cfm50):
    diff = Decimal(str(baseline_cfm50)) - Decimal(str(post_cfm50))
    return round_kwh(diff * SAVINGS_PER_CFM50_KWH)


# ---------------------------------------------------------------------------
# financing_amortization
# ---------------------------------------------------------------------------
def monthly_payment_cents(principal_cents, term_months, apr_bps):
    monthly_rate = Decimal(apr_bps) / Decimal(10000) / Decimal(12)
    if monthly_rate == 0:
        pay = Decimal(principal_cents) / Decimal(term_months)
    else:
        denom_pow = (Decimal(1) + monthly_rate) ** term_months
        factor = Decimal(1) - (Decimal(1) / denom_pow)
        pay = Decimal(principal_cents) * monthly_rate / factor
    return int(pay.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
