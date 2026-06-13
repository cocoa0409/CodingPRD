"""Calculation engine (PRD §3.4, §3.7, §3.9; SCAFFOLD §1.3).

All money is integer cents. Decimal is used for precision-sensitive rounding;
float is never used for money.
"""
import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

BPS_DENOMINATOR = 10000
PERIOD_DAYS = 30
RESALE_MARKUP_BPS = 3500
DEPOSIT_BPS = 2000
RESTOCKING_BPS = 1000


def _round_half_up(num, den):
    return int((Decimal(num) / Decimal(den)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _floor(num, den):
    return int((Decimal(num) / Decimal(den)).quantize(Decimal("1"), rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# loan_amount_from_appraisal (PRD §3.3 / SCAFFOLD loan_amount_from_appraisal)
# ---------------------------------------------------------------------------
def principal_from_appraisal(appraised_value_cents, loan_to_value_bps, max_principal_cents):
    """principal = min(floor(appraised * ltv_bps / 10000), max_principal)."""
    ltv_value = _floor(appraised_value_cents * loan_to_value_bps, BPS_DENOMINATOR)
    return min(ltv_value, max_principal_cents)


# ---------------------------------------------------------------------------
# per-period charge (PRD §3.4)
# ---------------------------------------------------------------------------
def per_period_charge(principal_cents, monthly_interest_bps, monthly_storage_fee_cents):
    """Round the interest portion half-up PER PERIOD, then add the flat storage fee."""
    interest = _round_half_up(principal_cents * monthly_interest_bps, BPS_DENOMINATOR)
    return interest + monthly_storage_fee_cents


# ---------------------------------------------------------------------------
# live_periods (PRD §3.4)
# ---------------------------------------------------------------------------
def live_periods(clock_dt, origination_at, periods_charged, max_periods_total):
    """ceil(elapsed_days / 30) clamped to [1, max_periods_total - periods_charged]."""
    elapsed_seconds = (clock_dt - origination_at).total_seconds()
    elapsed_days = math.floor(elapsed_seconds / 86400.0)
    if elapsed_days < 0:
        elapsed_days = 0
    raw = math.ceil(elapsed_days / PERIOD_DAYS)
    upper = max_periods_total - periods_charged
    if raw < 1:
        raw = 1
    if raw > upper:
        raw = upper
    return raw


# ---------------------------------------------------------------------------
# redemption_payoff (PRD §3.4 / SCAFFOLD redemption_payoff)
# ---------------------------------------------------------------------------
def redemption_payoff(loan, schedule, clock_dt):
    """Return (payoff_cents, total_periods, per_period_charge_cents)."""
    lp = live_periods(
        clock_dt,
        loan["origination_at"],
        loan["periods_charged"],
        schedule["max_periods_total"],
    )
    total_periods = loan["periods_charged"] + lp
    ppc = per_period_charge(
        loan["principal_cents"],
        schedule["monthly_interest_bps"],
        schedule["monthly_storage_fee_cents"],
    )
    payoff = loan["principal_cents"] + loan["setup_fee_cents"] + total_periods * ppc
    return payoff, total_periods, ppc


# ---------------------------------------------------------------------------
# resale_pricing (PRD §3.7 / SCAFFOLD resale_pricing)
# ---------------------------------------------------------------------------
def resale_prices(appraised_value_cents, cost_basis_cents):
    """Return (list_price_cents, floor_price_cents)."""
    markup_raw = Decimal(appraised_value_cents) * Decimal(BPS_DENOMINATOR + RESALE_MARKUP_BPS) / Decimal(BPS_DENOMINATOR)
    # round half-up to nearest whole DOLLAR (multiples of 100 cents)
    list_dollars = int((markup_raw / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    list_price = max(list_dollars * 100, cost_basis_cents)
    floor_price = cost_basis_cents
    return list_price, floor_price


# ---------------------------------------------------------------------------
# layaway_schedule (PRD §3.9 / SCAFFOLD layaway_schedule)
# ---------------------------------------------------------------------------
def layaway_deposit(total_price_cents):
    return _round_half_up(total_price_cents * DEPOSIT_BPS, BPS_DENOMINATOR)


def layaway_installments(total_price_cents, installment_count):
    """Return a list of installment amounts; final absorbs the remainder."""
    deposit = layaway_deposit(total_price_cents)
    remaining = total_price_cents - deposit
    base = _floor(remaining, installment_count)
    amounts = []
    for seq in range(1, installment_count + 1):
        if seq < installment_count:
            amounts.append(base)
        else:
            amounts.append(remaining - base * (installment_count - 1))
    return deposit, amounts


# ---------------------------------------------------------------------------
# layaway_default_refund (PRD §3.9 / SCAFFOLD layaway_default_refund)
# ---------------------------------------------------------------------------
def layaway_refund(total_price_cents, paid_cents):
    restocking = _round_half_up(total_price_cents * RESTOCKING_BPS, BPS_DENOMINATOR)
    return max(0, paid_cents - restocking)
