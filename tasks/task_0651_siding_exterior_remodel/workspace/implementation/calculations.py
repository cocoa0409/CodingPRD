"""Calculation rules (scaffold 1.3 / PRD 3.2-3.11).

All money is integer cents. Fractional cents resolve with round-half-up.
Areas stored to 2 decimal places (round-half-up). dti_ratio to 4 decimals.
Material order qty is ceil to whole sqft. financing monthly payment is ceil.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

# Constants (scaffold 1.3)
SALES_TAX_RATE = Decimal("0.0825")
RETAINAGE_RATE = Decimal("0.10")
RETAINAGE_CAP_RATE = Decimal("0.05")
DTI_MAX = Decimal("0.43")
APR_BY_TERM = {60: Decimal("0.0599"), 120: Decimal("0.0799"), 180: Decimal("0.0999")}


def _d(x):
    """Coerce to Decimal via str to avoid binary float artifacts."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def round_half_up_cents(value):
    """Round a Decimal to a whole integer (cents), round-half-up."""
    return int(_d(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round to a number with 2 decimal places, round-half-up; returns float."""
    return float(_d(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round_half_up_4dp(value):
    """Round to 4 decimal places, round-half-up; returns float."""
    return float(_d(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


# ----------------------------------------------------------------------------
# net_siding_area: max(gross - opening, 0), 2 decimals round-half-up
# ----------------------------------------------------------------------------
def net_siding_area(gross_wall_sqft, opening_sqft):
    net = _d(gross_wall_sqft) - _d(opening_sqft)
    if net < 0:
        net = Decimal("0")
    return round_half_up_2dp(net)


# ----------------------------------------------------------------------------
# line_extended_amount: SIDING applies waste factor; TRIM/WRAP do not.
# extended_cents = round_half_up(effective_qty * unit_price_cents), per line.
# ----------------------------------------------------------------------------
def line_extended_amount(scope_kind, quantity, unit_price_cents, waste_factor_pct):
    if scope_kind == "SIDING":
        effective_qty = _d(quantity) * (Decimal("1") + _d(waste_factor_pct))
    else:  # TRIM or WRAP
        effective_qty = _d(quantity)
    return round_half_up_cents(effective_qty * _d(unit_price_cents))


# ----------------------------------------------------------------------------
# estimate_subtotal / estimate_total: round per line FIRST (already done), then
# sum the rounded line amounts, then tax on the rounded subtotal.
# ----------------------------------------------------------------------------
def estimate_subtotal(line_items):
    return sum(li["extended_cents"] for li in line_items)


def estimate_total(line_subtotal_cents):
    tax = round_half_up_cents(_d(line_subtotal_cents) * SALES_TAX_RATE)
    total = line_subtotal_cents + tax
    return tax, total


# ----------------------------------------------------------------------------
# material_order_qty: ceil(net_siding_sqft * (1 + waste_factor_pct))
# ----------------------------------------------------------------------------
def material_order_qty(net_siding_sqft, waste_factor_pct):
    raw = _d(net_siding_sqft) * (Decimal("1") + _d(waste_factor_pct))
    return int(raw.to_integral_value(rounding=ROUND_CEILING))


# ----------------------------------------------------------------------------
# realized_contract_total: baseline + sum APPROVED change-order deltas
# ----------------------------------------------------------------------------
def realized_contract_total(baseline_total_cents, approved_deltas):
    return baseline_total_cents + sum(approved_deltas)


# ----------------------------------------------------------------------------
# draw_release_amount: gross, raw retainage, cumulative cap headroom, net.
# Each named step round-half-up to whole cents.
# ----------------------------------------------------------------------------
def draw_release_amount(contract_total_cents, milestone_pct, retainage_held_cents):
    gross = round_half_up_cents(_d(contract_total_cents) * _d(milestone_pct))
    raw_retainage = round_half_up_cents(_d(gross) * RETAINAGE_RATE)
    cap_total = round_half_up_cents(_d(contract_total_cents) * RETAINAGE_CAP_RATE)
    headroom = cap_total - retainage_held_cents
    if headroom < 0:
        headroom = 0
    retainage = min(raw_retainage, headroom)
    net = gross - retainage
    return gross, retainage, net


# ----------------------------------------------------------------------------
# financing_monthly_payment: amortized payment at the term's APR tier; ceil.
# ----------------------------------------------------------------------------
def financing_monthly_payment(requested_amount_cents, term_months):
    apr = APR_BY_TERM[term_months]
    monthly_rate = apr / Decimal("12")
    n = term_months
    P = _d(requested_amount_cents)
    if monthly_rate == 0:
        raw = P / Decimal(n)
    else:
        factor = (Decimal("1") + monthly_rate) ** n
        raw = P * monthly_rate * factor / (factor - Decimal("1"))
    # ceil to whole cents (lender rounds payment up)
    return int(raw.to_integral_value(rounding=ROUND_CEILING))


# ----------------------------------------------------------------------------
# financing_dti: (monthly_debt + monthly_payment) / monthly_income, 4dp half-up
# ----------------------------------------------------------------------------
def financing_dti(annual_income_cents, monthly_debt_cents, monthly_payment_cents):
    monthly_income = _d(annual_income_cents) / Decimal("12")
    if monthly_income == 0:
        # Avoid division by zero: treat as an unbounded ratio (will exceed DTI_MAX).
        return None
    ratio = (_d(monthly_debt_cents) + _d(monthly_payment_cents)) / monthly_income
    return round_half_up_4dp(ratio)


def dti_within_limit(dti_ratio):
    if dti_ratio is None:
        return False
    return _d(dti_ratio) <= DTI_MAX
