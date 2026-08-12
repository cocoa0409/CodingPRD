"""Calculation rules (PRD 2.8, 3.2, 3.3, 3.4, 3.7, 3.8, 3.10).

Every monetary quantity is an integer number of cents.  Fractional cents are
resolved by rounding half up -- to the nearest integer with ties resolved away
from zero, so round_half_up(-2.5) == -3.  `decimal.ROUND_HALF_UP` is exactly
that rule; Python's builtin round() is not, and is never used here.
"""

import datetime
import math
from decimal import ROUND_HALF_UP, Decimal

from constants import (
    CADENCE_ALLOWANCE_MULT,
    CADENCE_FEE_MULT,
    CADENCE_INTERVAL_DAYS,
    DAMAGE_MINUTES_ADD,
    DAMAGE_PRICE_MULT,
    LOANER_GRACE_HOURS,
    LOANER_LATE_FEE_CAP_CENTS,
    LOANER_LATE_FEE_PER_DAY_CENTS,
    PART_FEE_CENTS,
    PRORATION_BASIS_DAYS,
    REASSESS_AUTHORIZATION_ABS_CENTS,
    REASSESS_AUTHORIZATION_PCT_BP,
    RUSH_MIN_SURCHARGE_CENTS,
    RUSH_SURCHARGE_PCT,
    SERVICE_TAX_RATE_BP,
    SUBSCRIPTION_CYCLE_DAYS,
)

ONE = Decimal(1)


def round_half_up(value):
    """Round a Decimal to a whole integer, ties away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(ONE, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# subscription_effective_fee
# ---------------------------------------------------------------------------
def effective_monthly_fee(monthly_fee_cents, cadence):
    return round_half_up(Decimal(monthly_fee_cents) * Decimal(CADENCE_FEE_MULT[cadence]))


def included_items_this_cycle(included_items_per_cycle, cadence):
    return included_items_per_cycle * CADENCE_ALLOWANCE_MULT[cadence]


# ---------------------------------------------------------------------------
# next_service_date
# ---------------------------------------------------------------------------
def next_service_date(anchor_date, cadence, clock_date, variant):
    """ANCHORED takes the smallest n >= 0; RE_ANCHORED the smallest n >= 1."""
    interval = CADENCE_INTERVAL_DAYS[cadence]
    n = 0 if variant == "ANCHORED" else 1
    candidate = anchor_date + datetime.timedelta(days=n * interval)
    while candidate < clock_date:
        n += 1
        candidate = anchor_date + datetime.timedelta(days=n * interval)
    return candidate


def cycle_end_date(cycle_start_date):
    return cycle_start_date + datetime.timedelta(days=SUBSCRIPTION_CYCLE_DAYS)


# ---------------------------------------------------------------------------
# subscription_proration
# ---------------------------------------------------------------------------
def unused_days(clock_date, cycle_end):
    return max(0, (cycle_end - clock_date).days)


def pause_proration(effective_fee_cents, days_unused):
    """Always a credit: negative or zero."""
    return -round_half_up(
        Decimal(effective_fee_cents) * Decimal(days_unused) / Decimal(PRORATION_BASIS_DAYS)
    )


def cadence_change_proration(new_fee_cents, old_fee_cents, days_unused):
    """Prices the fee difference; positive up-cadencing, negative down."""
    return round_half_up(
        Decimal(new_fee_cents - old_fee_cents)
        * Decimal(days_unused)
        / Decimal(PRORATION_BASIS_DAYS)
    )


# ---------------------------------------------------------------------------
# item_service_minutes / item_service_price
# ---------------------------------------------------------------------------
def item_minutes(base_service_minutes, tier):
    return base_service_minutes + DAMAGE_MINUTES_ADD[tier]


def item_gross_cents(list_price_cents, tier):
    return round_half_up(Decimal(list_price_cents) * Decimal(DAMAGE_PRICE_MULT[tier]))


def part_fee_for(tier):
    if tier is None:
        return 0
    return PART_FEE_CENTS[tier]


def discounted_base(final_gross_cents, overage_discount_pct):
    return round_half_up(
        Decimal(final_gross_cents) * (ONE - Decimal(str(overage_discount_pct)))
    )


def rush_surcharge(base_cents):
    """max(500, round_half_up(base * 0.20)) -- the flat floor wins on cheap work."""
    pct = round_half_up(Decimal(base_cents) * Decimal(RUSH_SURCHARGE_PCT))
    return max(RUSH_MIN_SURCHARGE_CENTS, pct)


# ---------------------------------------------------------------------------
# item_reauthorization_required
# ---------------------------------------------------------------------------
def requires_reauthorization(final_gross_cents, quoted_gross_cents):
    delta = final_gross_cents - quoted_gross_cents
    return (delta > REASSESS_AUTHORIZATION_ABS_CENTS) and (
        delta * 10000 > quoted_gross_cents * REASSESS_AUTHORIZATION_PCT_BP
    )


# ---------------------------------------------------------------------------
# loaner_late_fee
# ---------------------------------------------------------------------------
def loaner_late_fee(due_at, returned_at, attribution):
    if attribution == "SERVICE":
        return 0
    grace_end = due_at + datetime.timedelta(hours=LOANER_GRACE_HOURS)
    overdue_seconds = (returned_at - grace_end).total_seconds()
    if overdue_seconds <= 0:
        return 0
    late_days = int(math.ceil(overdue_seconds / 86400.0))
    return min(LOANER_LATE_FEE_CAP_CENTS, late_days * LOANER_LATE_FEE_PER_DAY_CENTS)


# ---------------------------------------------------------------------------
# invoice_totals -- tax computed once over the aggregate taxable subtotal.
# ---------------------------------------------------------------------------
def invoice_tax(taxable_subtotal_cents, tax_exempt):
    if tax_exempt:
        return 0
    base = max(0, taxable_subtotal_cents)
    return round_half_up(Decimal(base) * Decimal(SERVICE_TAX_RATE_BP) / Decimal(10000))
