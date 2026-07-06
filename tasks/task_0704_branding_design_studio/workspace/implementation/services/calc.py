"""Calculation rules (PRD §2.5, §2.6, §3). All money is whole cents; non-integer
results are rounded half up. Decimal is used throughout — never float."""
import math

from util import mul_round_half_up

# Late-fee tier constants (PRD §3.6).
LATE_TIER1_RATE = "0.015"
LATE_TIER2_RATE = "0.030"
LATE_TIER1_MAX_DAYS = 30

# Retainer overage tier-1 cap (PRD §3.10).
TIER1_HOURS_CAP = 5


def provisional_deposit(base_scope_cents, deposit_pct):
    """round_half_up(base_scope_cents * deposit_pct), locked at activation."""
    return mul_round_half_up(base_scope_cents, deposit_pct)


def final_deposit(contract_value_cents, deposit_pct):
    """round_half_up(contract_value_cents * deposit_pct)."""
    return mul_round_half_up(contract_value_cents, deposit_pct)


def license_billable(cost_cents, markup_pct):
    """round_half_up(cost_cents * (1 + markup_pct)) — per line (PRD §3.7)."""
    from decimal import Decimal, ROUND_HALF_UP
    factor = Decimal("1") + Decimal(str(markup_pct))
    val = Decimal(str(cost_cents)) * factor
    return int(val.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def invoice_tax(taxable_cents, tax_rate):
    """round_half_up(taxable_cents * tax_rate); computed on credited base before
    any late fee (PRD §3.6)."""
    return mul_round_half_up(taxable_cents, tax_rate)


def days_overdue(clock_now, due_date):
    """Whole days overdue: elapsed time from due_date to now, rounded up to a
    whole number of days (PRD §3.6)."""
    delta = clock_now - due_date
    seconds = delta.total_seconds()
    if seconds <= 0:
        return 0
    return math.ceil(seconds / 86400.0)


def late_fee(net_before_fee, clock_now, due_date):
    """Tiered late fee on net-before-fee (PRD §3.6).

    days_overdue <= 0       -> 0
    days_overdue <= 30      -> round_half_up(net_before_fee * 0.015)
    days_overdue > 30       -> round_half_up(net_before_fee * 0.030)
    Boundary inclusive at 30.
    """
    d = days_overdue(clock_now, due_date)
    if d <= 0:
        return 0
    if d <= LATE_TIER1_MAX_DAYS:
        return mul_round_half_up(net_before_fee, LATE_TIER1_RATE)
    return mul_round_half_up(net_before_fee, LATE_TIER2_RATE)


def retainer_overage(hours_used, included_hours, tier1_rate_cents, tier2_rate_cents):
    """Tiered overage (PRD §3.10). Whole cents per whole hour — no rounding.

    raw_overage   = max(0, hours_used - included_hours)
    tier1_hours   = min(raw_overage, 5)
    tier2_hours   = max(0, raw_overage - 5)
    overage_cents = tier1_hours*tier1_rate + tier2_hours*tier2_rate
    """
    raw = max(0, hours_used - included_hours)
    tier1_hours = min(raw, TIER1_HOURS_CAP)
    tier2_hours = max(0, raw - TIER1_HOURS_CAP)
    return tier1_hours * tier1_rate_cents + tier2_hours * tier2_rate_cents
