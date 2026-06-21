"""All calculation rules (PRD §3, SCAFFOLD §1.3).

Money is integer cents throughout. Fractional intermediates are rounded with
round-half-up unless a step explicitly specifies an integer ceiling. We use
decimal.Decimal for any division/rounding to avoid float drift.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# ---- Constants (SCAFFOLD §1.3) --------------------------------------------
ASSEMBLY_FEE_PER_UNIT_CENTS = 4900
HAUL_AWAY_FEE_PER_UNIT_CENTS = 3500
THRESHOLD_FEE_CENTS = 7900
WHITE_GLOVE_FEE_CENTS = 19900
TAX_RATE_BPS = 825  # 8.25%

INSTALLMENT_APR_BPS = 1200  # 12% add-on APR, prorated by term_months/12
LEASE_MARKUP_NUM = 13
LEASE_MARKUP_DEN = 10  # 1.30x

MIN_CREDIT_SCORE_INSTALLMENT = 640
MIN_CREDIT_SCORE_LEASE_TO_OWN = 600
MAX_DTI_PCT = 43
MAX_OPEN_PLANS = 2

BASIC_RATE_BPS = 300
PREMIUM_RATE_BPS = 650

STANDARD_RETURN_WINDOW_DAYS = 30
MATTRESS_RETURN_WINDOW_DAYS = 100

RESTOCK_RATE_BPS = 1500  # 15%

WHITE_GLOVE_BUFFER_MINUTES = 30


def round_half_up(value):
    """Round a Decimal/number to the nearest integer, half rounds up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# OrderLine prices
# ---------------------------------------------------------------------------
def line_unit_config_price(product, fabric_code, size_code):
    """base_price + chosen fabric surcharge + chosen size surcharge."""
    fabric_surcharge = _option_surcharge(product["available_fabrics"], fabric_code)
    size_surcharge = _option_surcharge(product["available_sizes"], size_code)
    return product["base_price_cents"] + fabric_surcharge + size_surcharge


def _option_surcharge(options, code):
    for opt in options:
        if opt.get("code") == code:
            return int(opt.get("surcharge_cents", 0))
    return 0


def line_addon_fee(add_assembly, add_haul_away, quantity):
    assembly_fee = ASSEMBLY_FEE_PER_UNIT_CENTS * quantity if add_assembly else 0
    haul_fee = HAUL_AWAY_FEE_PER_UNIT_CENTS * quantity if add_haul_away else 0
    return assembly_fee + haul_fee


# ---------------------------------------------------------------------------
# Order totals
# ---------------------------------------------------------------------------
def order_merchandise_subtotal(active_lines):
    return sum(line["line_total_cents"] for line in active_lines)


def order_service_total(delivery_tier, active_lines):
    delivery_fee = WHITE_GLOVE_FEE_CENTS if delivery_tier == "WHITE_GLOVE" else THRESHOLD_FEE_CENTS
    addon_total = sum(line["addon_fee_cents"] for line in active_lines)
    return delivery_fee + addon_total


def order_grand_total(merchandise_subtotal, service_total):
    """Pinned order: taxable_base = merch + service; tax computed ONCE
    (sum-then-round) on the combined base; total = base + tax.
    """
    taxable_base = merchandise_subtotal + service_total
    tax = round_half_up(Decimal(taxable_base) * TAX_RATE_BPS / Decimal(10000))
    return taxable_base + tax


# ---------------------------------------------------------------------------
# Financing schedule
# ---------------------------------------------------------------------------
def financing_schedule(plan_type, principal, term_months):
    """Return (total_of_payments_cents, monthly_payment_cents)."""
    if plan_type == "INSTALLMENT":
        interest = round_half_up(
            Decimal(principal) * INSTALLMENT_APR_BPS / Decimal(10000)
            * Decimal(term_months) / Decimal(12)
        )
        total = principal + interest
    else:  # LEASE_TO_OWN
        total = round_half_up(Decimal(principal) * LEASE_MARKUP_NUM / Decimal(LEASE_MARKUP_DEN))
    monthly = _ceil_div(total, term_months)
    return total, monthly


def installment_total_interest(plan):
    """Total interest baked into an INSTALLMENT plan's total_of_payments."""
    return plan["total_of_payments_cents"] - plan["financed_principal_cents"]


def _ceil_div(numerator, denominator):
    """Integer ceiling of numerator/denominator (both integers)."""
    return -((-numerator) // denominator)


# ---------------------------------------------------------------------------
# Payoff balance (per plan_type)
# ---------------------------------------------------------------------------
def financing_payoff_balance(plan):
    paid = plan["paid_to_date_cents"]
    total = plan["total_of_payments_cents"]
    if plan["plan_type"] == "INSTALLMENT":
        term = plan["term_months"]
        made = plan["payments_made_count"]
        periods_remaining = term - made
        total_interest = installment_total_interest(plan)
        unearned = round_half_up(
            Decimal(total_interest) * periods_remaining * (periods_remaining + 1)
            / Decimal(term * (term + 1))
        )
        balance = (total - paid) - unearned
    else:  # LEASE_TO_OWN
        balance = total - paid
    return max(balance, 0)


# ---------------------------------------------------------------------------
# Eligibility gates (DTI uses exact integer comparison)
# ---------------------------------------------------------------------------
def credit_floor(plan_type):
    return MIN_CREDIT_SCORE_INSTALLMENT if plan_type == "INSTALLMENT" else MIN_CREDIT_SCORE_LEASE_TO_OWN


def dti_within_limit(existing_obligations_cents, monthly_payment_cents, monthly_income_cents):
    """(obligations + monthly) * 100 <= MAX_DTI_PCT * income."""
    lhs = (existing_obligations_cents + monthly_payment_cents) * 100
    rhs = MAX_DTI_PCT * monthly_income_cents
    return lhs <= rhs


# ---------------------------------------------------------------------------
# Protection premium
# ---------------------------------------------------------------------------
def protection_premium(covered_line_total, tier, coverage_years):
    rate_bps = PREMIUM_RATE_BPS if tier == "PREMIUM" else BASIC_RATE_BPS
    return round_half_up(
        Decimal(covered_line_total) * rate_bps / Decimal(10000) * coverage_years
    )


# ---------------------------------------------------------------------------
# Return refund
# ---------------------------------------------------------------------------
def return_window_days(category):
    return MATTRESS_RETURN_WINDOW_DAYS if category == "MATTRESS" else STANDARD_RETURN_WINDOW_DAYS


def return_refund(gross, reason):
    """Return (restocking_fee_cents, refund_amount_cents)."""
    if reason in ("DAMAGED", "DEFECTIVE"):
        restocking_fee = 0
    else:  # CHANGED_MIND
        restocking_fee = round_half_up(Decimal(gross) * RESTOCK_RATE_BPS / Decimal(10000))
    refund = gross - restocking_fee
    return restocking_fee, refund
