"""Calculation rules (SCAFFOLD 1.3 / PRD 2.6, 3.4, 3.6, 3.7).

All money is integer cents. The only rounding operation in the system is the
platform fee on a close, which uses round-half-up to the nearest whole cent.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# investor_annual_limit constants
FLOOR_CENTS = 250000      # $2,500
CAP_CENTS = 12400000      # $124,000

# trailing windows
WINDOW_DAYS = 365

# close_disbursement
FEE_BPS = 750             # 7.5% platform fee

# issuer cap
ISSUER_CAP_CENTS = 500000000   # $5,000,000


def investor_annual_limit(annual_income_cents, net_worth_cents):
    """Reg CF (2021 amended) per-investor 12-month limit in integer cents.

    if both income and net worth >= CAP_CENTS:  10% of the LESSER
    else:                                       5%  of the GREATER
    then clamp into [FLOOR_CENTS, CAP_CENTS].
    """
    lesser = min(annual_income_cents, net_worth_cents)
    greater = max(annual_income_cents, net_worth_cents)
    if annual_income_cents >= CAP_CENTS and net_worth_cents >= CAP_CENTS:
        pct = (lesser * 10) // 100
    else:
        pct = (greater * 5) // 100
    return min(max(FLOOR_CENTS, pct), CAP_CENTS)


def round_half_up_fee(batch_gross_cents):
    """Platform fee = round_half_up( batch_gross * FEE_BPS / 10000 ), computed
    once on the batch SUM (NOT per-investment)."""
    raw = Decimal(batch_gross_cents) * Decimal(FEE_BPS) / Decimal(10000)
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def equity_issuance(amount_cents, security_type, price_per_security_cents):
    """Returns (securities_issued, consideration_cents, refund_remainder_cents,
    instrument, quantity, principal_cents) for one swept investment."""
    if security_type == "EQUITY":
        securities_issued = amount_cents // price_per_security_cents
        consideration = securities_issued * price_per_security_cents
        remainder = amount_cents - consideration
        return securities_issued, consideration, remainder, "EQUITY", securities_issued, consideration
    else:  # SAFE
        return 0, 0, 0, "SAFE", None, amount_cents


def window_start(now_dt):
    """Inclusive lower bound of a trailing 365-day window relative to now."""
    return now_dt - timedelta(days=WINDOW_DAYS)
