"""Calculation rules (PRD Sections 2.5, 3.1, 3.4, 3.6, 3.7)."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up_div(numer, denom):
    """round_half_up(numer / denom) -> int (integer cents)."""
    return int((Decimal(numer) / Decimal(denom)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ami_pct(annual_income_cents, ami_100_income_cents):
    """Reporting figure: income / ami100 * 100, round half-up to 2 decimals.

    Returned as a Decimal quantized to 2dp.
    """
    val = (Decimal(annual_income_cents) * 100) / Decimal(ami_100_income_cents)
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def income_ceiling_cents(ami_100_income_cents, ami_limit_pct):
    """floor(ami100 * ami_limit_pct / 100) — exact integer cents."""
    return (ami_100_income_cents * ami_limit_pct) // 100


def is_eligible(annual_income_cents, ami_100_income_cents, ami_limit_pct):
    return annual_income_cents <= income_ceiling_cents(ami_100_income_cents, ami_limit_pct)


def tier_pct(ami_pct_dec):
    """Minimum-contribution tier percentage selected from the reporting ami_pct."""
    p = Decimal(ami_pct_dec)
    if p <= Decimal("50.00"):
        return 0
    if p <= Decimal("65.00"):
        return 1
    if p <= Decimal("80.00"):
        return 3
    # Above 80.00 the highest tier carries forward.
    return 3


def _ceil_div(numer, denom):
    if numer <= 0:
        return 0
    return -((-numer) // denom)


def assistance_amount(basis_cents, first_mortgage_cents, stated_contribution_cents,
                      ami_pct_dec, max_assistance_cents):
    """Provisional/final assistance in whole cents (variants differ only in inputs)."""
    tp = tier_pct(ami_pct_dec)
    required_contribution = max(stated_contribution_cents, _ceil_div(basis_cents * tp, 100))
    funding_gap = basis_cents - first_mortgage_cents - required_contribution
    return min(max_assistance_cents, max(0, funding_gap))


def appreciation_cents(sale_price_cents, basis_value_cents):
    return max(0, sale_price_cents - basis_value_cents)


def shared_appreciation_recapture(original_disbursed_cents, appreciation, share_pct):
    """recapture = principal + round_half_up(share_pct/100 * appreciation); forgiven = 0."""
    share = round_half_up_div(share_pct * appreciation, 100)
    recapture = original_disbursed_cents + share
    return recapture, 0


def full_calendar_months(opened_at, sale_date):
    """Number of full calendar months from opened_at to sale_date (floored)."""
    months = (sale_date.year - opened_at.year) * 12 + (sale_date.month - opened_at.month)
    open_tail = (opened_at.day, opened_at.hour, opened_at.minute,
                 opened_at.second, opened_at.microsecond)
    sale_tail = (sale_date.day, sale_date.hour, sale_date.minute,
                 sale_date.second, sale_date.microsecond)
    if sale_tail < open_tail:
        months -= 1
    return max(0, months)


def declining_balance_recapture(original_disbursed_cents, months_held, term_months):
    """forgiven = round_half_up(original * min(months, term) / term); recapture = original - forgiven.

    Single final rounding on the whole product (sum-then-round).
    """
    capped = min(months_held, term_months)
    forgiven = round_half_up_div(original_disbursed_cents * capped, term_months)
    recapture = original_disbursed_cents - forgiven
    return recapture, forgiven
