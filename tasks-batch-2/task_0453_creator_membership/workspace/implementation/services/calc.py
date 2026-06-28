"""Calculation rules (SCAFFOLD §1.3, PRD §2.8, §3.4, §3.6, §3.7).

All money is integer cents; non-integer results are rounded HALF UP
(0.5 rounds up) — PRD §2.8. Never use float for the rounding decision; use
decimal.Decimal with ROUND_HALF_UP.
"""
import calendar
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# Constants (SCAFFOLD §1.3)
PROCESSING_PCT_RATE = Decimal("0.029")
PROCESSING_FLAT_CENTS = 30
FEE_RATE = {
    "STARTER": Decimal("0.10"),
    "PRO": Decimal("0.08"),
    "PREMIUM": Decimal("0.05"),
}
GRACE_PERIOD_DAYS = 7
WIN_BACK_WINDOW_DAYS = 60


def round_half_up(value):
    """Round a Decimal to the nearest whole cent, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def initial_proration(base_cents, anchor_dt):
    """Forward-looking proration (SCAFFOLD calc initial_proration; PRD §3.4).

    remaining_days = days_in_month - (day_of_month - 1)
      -> the anchor day itself counts as remaining.
    prorated = round_half_up(base * remaining_days / days_in_month)

    base may be negative on a downgrade delta; round_half_up handles it via
    Decimal arithmetic.
    """
    year = anchor_dt.year
    month = anchor_dt.month
    days_in_month = calendar.monthrange(year, month)[1]
    day_of_month = anchor_dt.day
    remaining_days = days_in_month - (day_of_month - 1)
    raw = Decimal(base_cents) * Decimal(remaining_days) / Decimal(days_in_month)
    return round_half_up(raw)


def processing_fee(net_amount_cents):
    """Processing fee for one charge (SCAFFOLD calc processing_fee; PRD §3.7).

    net == 0  -> 0
    else      -> round_half_up(net * 0.029) + 30
    Rounded PER LINE before any later summation.
    """
    if net_amount_cents == 0:
        return 0
    pct = round_half_up(Decimal(net_amount_cents) * PROCESSING_PCT_RATE)
    return pct + PROCESSING_FLAT_CENTS


def platform_fee(gross_cents, platform_plan):
    """Platform commission, rounded once over the whole gross (PRD §3.7)."""
    rate = FEE_RATE[platform_plan]
    return round_half_up(Decimal(gross_cents) * rate)


def per_creation_charge(per_creation_fee_cents, monthly_cap_cents, current_cycle_charged_cents):
    """Per-creation charge respecting the monthly cap (SCAFFOLD calc
    per_creation_charge; PRD §3.6).

    remaining_cap = max(0, cap - current_cycle_charged_cents)
    charge_amount = min(per_creation_fee_cents, remaining_cap)
    charge_amount == 0 -> no charge row created (caller handles).
    """
    remaining_cap = max(0, monthly_cap_cents - current_cycle_charged_cents)
    return min(per_creation_fee_cents, remaining_cap)


def win_back_first_charge(monthly_fee_cents, anchor_dt, discount_pct):
    """Win-back reactivation first charge (SCAFFOLD calc win_back_first_charge;
    PRD §3.6).

    Evaluation order PINNED: prorate FIRST, then discount the prorated base.
    step1 = initial_proration(monthly_fee_cents)
    gross = round_half_up(step1 * (1 - discount_pct))
    """
    step1 = initial_proration(monthly_fee_cents, anchor_dt)
    if discount_pct is None:
        discount_pct = 0
    factor = Decimal(1) - Decimal(str(discount_pct))
    return round_half_up(Decimal(step1) * factor)


def grace_deadline(current_clock):
    """current_clock + GRACE_PERIOD_DAYS (PRD §3.3)."""
    return current_clock + timedelta(days=GRACE_PERIOD_DAYS)


def win_back_offer_expiry(lapsed_at):
    """lapsed_at + WIN_BACK_WINDOW_DAYS (PRD §3.6)."""
    return lapsed_at + timedelta(days=WIN_BACK_WINDOW_DAYS)
