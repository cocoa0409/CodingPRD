"""Calculation rules (§3 / §1.3). All money in integer cents, Decimal math."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

AGE_CAP = 90
MIN_AGE = 62
BPS_DIVISOR = Decimal(10000)
MONTHS_PER_YEAR = Decimal(12)
TENURE_TERMINAL_AGE = 100
NON_RECOURSE_FACTOR_PCT = Decimal(95)


def round_half_up(value):
    """Round a Decimal to the nearest whole integer, halves up (away from
    zero for positive magnitudes)."""
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def floor_int(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_FLOOR))


def whole_years_between(birthdate_str, ref_date):
    """Whole completed years between birthdate (YYYY-MM-DD) and ref_date
    (a datetime.date), floored to whole years."""
    bd = _parse_date(birthdate_str)
    years = ref_date.year - bd.year
    # subtract one if the anniversary hasn't occurred yet this year
    if (ref_date.month, ref_date.day) < (bd.month, bd.day):
        years -= 1
    return years


def _parse_date(s):
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


# ---------------------------------------------------------------------------
# principal_limit
# ---------------------------------------------------------------------------
def max_claim_amount(appraised_value_cents, hud_lending_limit_cents):
    return min(appraised_value_cents, hud_lending_limit_cents)


def select_plf(plf_rows, expected_rate_bps, borrower_age):
    """plf_rows: iterable of PrincipalLimitFactor dicts for the lender.
    Match on expected_rate_bps bucket and the borrower's age (capped at 90).
    Exact-age row preferred; else greatest age <= capped age. None if none."""
    lookup_age = min(borrower_age, AGE_CAP)
    candidates = [r for r in plf_rows
                  if r["expected_rate_bps"] == expected_rate_bps and r["age"] <= lookup_age]
    if not candidates:
        return None
    # greatest age <= lookup_age (exact age is naturally the max if present)
    return max(candidates, key=lambda r: r["age"])


def gross_principal_limit(max_claim_cents, plf_micros):
    product = Decimal(max_claim_cents) * Decimal(plf_micros) / Decimal(1000000)
    return round_half_up(product)


# ---------------------------------------------------------------------------
# lesa_sizing
# ---------------------------------------------------------------------------
def lesa_initial_amount(funding_mode, annual_property_charge_cents, life_expectancy_years):
    full = Decimal(annual_property_charge_cents) * Decimal(life_expectancy_years)
    if funding_mode == "FULLY_FUNDED":
        return int(full)
    # PARTIALLY_FUNDED: half the horizon, round half up
    return round_half_up(full / Decimal(2))


# ---------------------------------------------------------------------------
# scheduled_payment (TENURE / TERM) — floor
# ---------------------------------------------------------------------------
def scheduled_payment(net_principal_limit_cents, expected_rate_bps, draw_type,
                      tenure_term_months, borrower_age):
    principal = Decimal(net_principal_limit_cents)
    monthly_rate = (Decimal(expected_rate_bps) / BPS_DIVISOR) / MONTHS_PER_YEAR
    if draw_type == "TENURE":
        n = (TENURE_TERMINAL_AGE - borrower_age) * 12
    else:  # TERM
        n = tenure_term_months
    if n <= 0:
        return 0
    if monthly_rate == 0:
        return floor_int(principal / Decimal(n))
    numerator = principal * monthly_rate
    denominator = Decimal(1) - (Decimal(1) + monthly_rate) ** (-n)
    return floor_int(numerator / denominator)


# ---------------------------------------------------------------------------
# balance_accrual (round-per-period-then-accumulate)
# ---------------------------------------------------------------------------
def accrual_components(principal_balance_cents, expected_rate_bps, annual_mip_rate_bps):
    """One month's rounded interest + MIP components from the current balance."""
    bal = Decimal(principal_balance_cents)
    interest = round_half_up(bal * (Decimal(expected_rate_bps) / BPS_DIVISOR / MONTHS_PER_YEAR))
    mip = round_half_up(bal * (Decimal(annual_mip_rate_bps) / BPS_DIVISOR / MONTHS_PER_YEAR))
    return interest, mip


def line_growth(available_line_cents, expected_rate_bps, annual_mip_rate_bps):
    """One month's line-of-credit growth, rounded half up."""
    combined = (Decimal(expected_rate_bps) + Decimal(annual_mip_rate_bps)) / BPS_DIVISOR / MONTHS_PER_YEAR
    return round_half_up(Decimal(available_line_cents) * combined)


def projected_balance(principal_balance_cents, expected_rate_bps, annual_mip_rate_bps,
                      number_of_months):
    """Forward payoff-quote projection (accumulate-then-round)."""
    combined = (Decimal(expected_rate_bps) + Decimal(annual_mip_rate_bps)) / BPS_DIVISOR / MONTHS_PER_YEAR
    factor = (Decimal(1) + combined) ** number_of_months
    return round_half_up(Decimal(principal_balance_cents) * factor)


# ---------------------------------------------------------------------------
# lesser_of_payoff
# ---------------------------------------------------------------------------
def lesser_of_payoff(principal_balance_cents, basis_value_cents):
    capped = round_half_up(NON_RECOURSE_FACTOR_PCT * Decimal(basis_value_cents) / Decimal(100))
    payoff = min(principal_balance_cents, capped)
    deficiency = principal_balance_cents - payoff
    return payoff, deficiency
