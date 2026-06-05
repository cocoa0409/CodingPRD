from decimal import Decimal, ROUND_HALF_UP

LATE_FEE_PCT = Decimal("0.05")
LATE_FEE_MIN_CENTS = 2500
DEFAULT_THRESHOLD = 3


def _D(x):
    # Build a Decimal that exactly represents the supplied value. For floats
    # (rates carried at supplied precision) str() yields the intended literal.
    if isinstance(x, Decimal):
        return x
    if isinstance(x, float):
        return Decimal(str(x))
    return Decimal(x)


def round_half_up(value):
    """Round a Decimal to a whole integer of cents, half rounds up."""
    return int(_D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fico_tier(fico_score, rate_card):
    """Descending ladder of inclusive lower bounds."""
    if fico_score >= rate_card["tier_1_min_fico"]:
        return "TIER_1"
    if fico_score >= rate_card["tier_2_min_fico"]:
        return "TIER_2"
    if fico_score >= rate_card["tier_3_min_fico"]:
        return "TIER_3"
    return "TIER_4"


def apr_for_tier(tier, rate_card):
    return {
        "TIER_1": rate_card["tier_1_apr"],
        "TIER_2": rate_card["tier_2_apr"],
        "TIER_3": rate_card["tier_3_apr"],
        "TIER_4": rate_card["tier_4_apr"],
    }[tier]


def loan_monthly_payment(financed_principal_cents, apr, term_months):
    """Standard amortized level payment. Round half-up only on the final figure."""
    P = _D(financed_principal_cents)
    i = _D(apr) / Decimal(12)
    n = term_months
    if i == 0:
        payment = P / Decimal(n)
    else:
        factor = (Decimal(1) + i) ** n
        payment = P * (i * factor) / (factor - Decimal(1))
    return round_half_up(payment)


def loan_principal_balance(financed_principal_cents, apr, monthly_payment_cents,
                           payments_made_count):
    """Actuarial scheduled balance after payments_made_count posted payments.
    Interest is rounded per period before subtraction."""
    bal = _D(financed_principal_cents)
    i = _D(apr) / Decimal(12)
    mp = _D(monthly_payment_cents)
    for _ in range(payments_made_count):
        interest = Decimal(round_half_up(bal * i))
        principal = mp - interest
        bal = bal - principal
    return round_half_up(bal)


def loan_payoff_quotes(financed_principal_cents, apr, monthly_payment_cents,
                       term_months, payments_made_count):
    actuarial = loan_principal_balance(
        financed_principal_cents, apr, monthly_payment_cents, payments_made_count)
    gross = monthly_payment_cents * (term_months - payments_made_count)
    unearned = gross - actuarial
    return actuarial, gross, unearned


def loan_late_fee(monthly_payment_cents):
    pct = round_half_up(_D(monthly_payment_cents) * LATE_FEE_PCT)
    return max(LATE_FEE_MIN_CENTS, pct)


def lease_monthly_payment(sale_price_cents, residual_value_cents, down_payment_cents,
                          term_months, lease_money_factor, lease_tax_rate):
    """Base and tax each rounded independently from the same unrounded pre-tax sum."""
    adjusted_cap_cost = _D(sale_price_cents) - _D(down_payment_cents)
    depreciation_fee = (adjusted_cap_cost - _D(residual_value_cents)) / Decimal(term_months)
    finance_fee = (adjusted_cap_cost + _D(residual_value_cents)) * _D(lease_money_factor)
    pre_tax = depreciation_fee + finance_fee
    base_monthly = round_half_up(pre_tax)
    lease_tax = round_half_up(pre_tax * _D(lease_tax_rate))
    monthly_payment = base_monthly + lease_tax
    adjusted_cap_cost_cents = int(adjusted_cap_cost)
    return adjusted_cap_cost_cents, base_monthly, monthly_payment


def lease_mileage_overage(per_year_excess_miles, per_mile_overage_rate_cents):
    """Round each lease-year's charge to whole cents, then sum."""
    total = 0
    for miles in per_year_excess_miles:
        total += round_half_up(_D(miles) * _D(per_mile_overage_rate_cents))
    return total


def gap_deficiency(principal_balance_cents, insurance_settlement_cents):
    return max(0, principal_balance_cents - insurance_settlement_cents)
