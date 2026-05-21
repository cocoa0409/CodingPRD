"""Pure calculations: round_half_up, RCP, payoff projection.

All money is integer cents. Floats are only used as fixed rate multipliers; every
product is immediately converted to a Decimal and rounded HALF_UP to whole cents.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, List

from app.timeutil import add_months, parse_iso


# Locked benchmark constants (see SCAFFOLD calculations.monthly_accrual)
MONTHLY_INTEREST_RATE = Decimal("0.006667")
MONTHLY_FTP_RATE_NON_IA = Decimal("0.005")
MONTHLY_FTP_RATE_IA = Decimal("0.0025")


def round_half_up_to_cents(value) -> int:
    """Round any numeric value (Decimal, int, float-coerced) HALF_UP to whole cents."""
    if isinstance(value, Decimal):
        d = value
    elif isinstance(value, int):
        return value
    else:
        d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def interest_for_cycle(base_cents: int) -> int:
    return round_half_up_to_cents(Decimal(base_cents) * MONTHLY_INTEREST_RATE)


def penalty_for_cycle(base_cents: int, status: str) -> int:
    if status == "OPEN":
        rate = MONTHLY_FTP_RATE_NON_IA
    elif status == "IN_AGREEMENT":
        rate = MONTHLY_FTP_RATE_IA
    else:  # CNC, EXPIRED, PAID, etc.
        return 0
    return round_half_up_to_cents(Decimal(base_cents) * rate)


# ---------------------------------------------------------------------------
# Reasonable Collection Potential (§3.9, calc rcp_calculation)
# ---------------------------------------------------------------------------

LUMP_SUM_FACTOR = 12
PERIODIC_FACTOR = 24


def rcp_cents(monthly_disposable_income_cents: int, schedule_months: int,
              equity_cents: int = 0) -> int:
    """RCP = (max(0, MDI) * FACTOR) + equity, rounded HALF_UP to whole cents.

    Rounding is applied once at the final sum (intermediate values are NOT rounded).
    """
    factor = LUMP_SUM_FACTOR if schedule_months <= 5 else PERIODIC_FACTOR
    mdi = max(0, monthly_disposable_income_cents)
    future_income = Decimal(mdi) * Decimal(factor)
    equity = Decimal(max(0, equity_cents))
    total = future_income + equity
    return round_half_up_to_cents(total)


# ---------------------------------------------------------------------------
# Payoff projection (§3.6, calc payoff_projection)
# ---------------------------------------------------------------------------

def project_payoff(initial_balance_cents: int, monthly_payment_cents: int,
                   activation_iso: str, csed_effective_min_iso: str,
                   agreement_type: str):
    """Simulate forward month-by-month; return ISO 8601 UTC planned_payoff_date.

    Ordering pinned (per scaffold): interest first, then penalty, then add.
    For PPIA: cap at MAX_PROJECTION_MONTHS = 120; if balance > 0 at cap, return min CSED.
    """
    activation_dt = parse_iso(activation_iso)
    balance = initial_balance_cents
    months = 0
    MAX_PROJECTION_MONTHS = 120

    while True:
        if balance <= 0:
            break
        months += 1
        # Interest first, then penalty, both rounded individually, then added.
        interest = round_half_up_to_cents(Decimal(balance) * MONTHLY_INTEREST_RATE)
        penalty = round_half_up_to_cents(Decimal(balance) * MONTHLY_FTP_RATE_IA)
        balance += interest + penalty
        balance -= min(balance, monthly_payment_cents)
        if balance == 0:
            return _fmt(add_months(activation_dt, months))
        if months >= MAX_PROJECTION_MONTHS:
            if agreement_type == "PPIA":
                return csed_effective_min_iso
            # SHORT_TERM/LONG_TERM should not realistically reach this; safeguard.
            return _fmt(add_months(activation_dt, months))

    return _fmt(add_months(activation_dt, months))


def _fmt(dt) -> str:
    from app.timeutil import fmt
    return fmt(dt)
