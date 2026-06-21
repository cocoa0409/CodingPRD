"""Calculation rules (SCAFFOLD Table 3, PRD §3.6/§3.8/§3.9/§3.10/§3.11).

All money is integer cents; all rates are integer basis points. Wherever an
amount is multiplied by a basis-point rate, divide by 10,000 and round half up.
We use Decimal with ROUND_HALF_UP — never float (PRD §2.7).
"""
from decimal import Decimal, ROUND_HALF_UP

# Constants from SCAFFOLD Table 3.
FMV_BAND_SHORT_BPS = 2000   # term <= 24 months -> 20%
FMV_BAND_MID_BPS = 1500     # 24 < term <= 48  -> 15%
FMV_BAND_LONG_BPS = 1000    # term > 48        -> 10%
DOLLAR_OUT_RESIDUAL_CENTS = 100
TRAC_FLOOR_BPS = 1000

PRIME_FLOOR = 720
NEAR_PRIME_FLOOR = 640
APPROVAL_SCORE_FLOOR = 580

ANNUAL_DEPRECIATION_PCT = Decimal("0.10")
RESIDUAL_FLOOR_PCT = Decimal("0.20")

UCC_LAPSE_MONTHS = 60
SERIAL_REUSE_BUFFER_DAYS = 30


def round_half_up(value):
    """Round a Decimal to the nearest whole integer, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def bps_amount(amount_cents, rate_bps):
    """round_half_up(amount_cents * rate_bps / 10000)."""
    return round_half_up(Decimal(amount_cents) * Decimal(rate_bps) / Decimal(10000))


def monthly_payment(equipment_cost_cents, monthly_rate_factor_bps):
    """§1.3 monthly_payment: round_half_up(cost * rate_factor_bps / 10000)."""
    return bps_amount(equipment_cost_cents, monthly_rate_factor_bps)


def financed_amount(equipment_cost_cents, advance_payment_count, mp_cents, security_deposit_cents):
    """§1.3 financed_amount: cost - advance*mp - deposit (all integer, no rounding)."""
    return equipment_cost_cents - (advance_payment_count * mp_cents) - security_deposit_cents


def residual_value(lease_type, term_months, equipment_cost_cents, trac_residual_pct_bps):
    """§1.3 residual_value, dual-variant by lease_type."""
    if lease_type == "DOLLAR_OUT":
        return DOLLAR_OUT_RESIDUAL_CENTS
    if lease_type == "FMV":
        if term_months <= 24:
            band_bps = FMV_BAND_SHORT_BPS
        elif term_months <= 48:
            band_bps = FMV_BAND_MID_BPS
        else:
            band_bps = FMV_BAND_LONG_BPS
        return bps_amount(equipment_cost_cents, band_bps)
    if lease_type == "TRAC":
        return bps_amount(equipment_cost_cents, trac_residual_pct_bps)
    return 0


def buyout_quote(lease):
    """§1.3 buyout_quote, dual-variant by lease_type."""
    remaining = lease["term_months"] - lease["paid_installment_count"] - lease["advance_payment_count"]
    if remaining < 0:
        remaining = 0
    remaining_rent = remaining * lease["monthly_payment_cents"]
    ltype = lease["lease_type"]
    if ltype == "DOLLAR_OUT":
        return 100
    if ltype == "FMV":
        return lease["residual_value_cents"] + remaining_rent
    if ltype == "TRAC":
        return lease["residual_value_cents"]
    return 0


def invoice_sales_tax(base_rent_cents, sales_tax_rate_bps):
    """§1.3 invoice_sales_tax: per-invoice round_half_up on this invoice's base rent."""
    return bps_amount(base_rent_cents, sales_tax_rate_bps)


def assessment_tax_amount(taxable_base_cents, rate_bps):
    return bps_amount(taxable_base_cents, rate_bps)


def assessed_value(original_cost_cents, months_in_service):
    """§1.3 assessed_value: straight-line annual depreciation floored at 20%.

    years_in_service = floor(months_in_service / 12)
    depreciated = cost - round_half_up(cost * 0.10 * years)
    floor = round_half_up(cost * 0.20)
    assessed = max(depreciated, floor)   (floor applied AFTER depreciation)
    """
    years = months_in_service // 12
    depreciation = round_half_up(Decimal(original_cost_cents) * ANNUAL_DEPRECIATION_PCT * Decimal(years))
    depreciated = original_cost_cents - depreciation
    floor_cents = round_half_up(Decimal(original_cost_cents) * RESIDUAL_FLOOR_PCT)
    return max(depreciated, floor_cents)


def addon_incremental_payment(added_cost_cents, monthly_rate_factor_bps, remaining_scheduled):
    """§1.3 addon_incremental_payment: 0 when no SCHEDULED line remains."""
    if remaining_scheduled == 0:
        return 0
    return bps_amount(added_cost_cents, monthly_rate_factor_bps)


def remarketing_gain_loss(sale_proceeds_cents, residual_value_cents):
    """§1.3 remarketing_gain_loss: proceeds - residual (signed)."""
    return sale_proceeds_cents - residual_value_cents


def pricing_tier(credit_score):
    """§1.3 pricing_tier from credit_score at approval (>= boundaries)."""
    if credit_score >= PRIME_FLOOR:
        return "PRIME"
    if credit_score >= NEAR_PRIME_FLOOR:
        return "NEAR_PRIME"
    return "SUBPRIME"
