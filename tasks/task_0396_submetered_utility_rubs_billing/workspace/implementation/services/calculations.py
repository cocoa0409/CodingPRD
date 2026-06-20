"""Calculation rules (SCAFFOLD §1.3 / PRD §3.4, §3.7, §3.8, §3.10).

All money is integer cents. Percentages are floored except where a rule names a
different direction (late-fee percentage base is ceiled). Decimal is used for
exact percentage products.
"""

import math
from decimal import Decimal

# Constants (SCAFFOLD §1.3).
HIGH_READING_MULTIPLE = 3
NET_DAYS = 21
GRACE_DAYS = 5
COLLECTIONS_GRACE_DAYS = 30
MAX_REOPENS = 2

LATE_FEE_PCT = Decimal("0.05")
LATE_FEE_FLAT_CENTS = 500
LATE_FEE_MAX_CENTS = 5000
LATE_FEE_MAX_PCT = Decimal("0.10")


def _to_decimal(value):
    return Decimal(str(value))


def floor_pct(amount_cents, pct):
    """floor(amount_cents * pct) with exact decimal math."""
    return int((_to_decimal(amount_cents) * _to_decimal(pct)).to_integral_value(rounding="ROUND_FLOOR"))


def vendor_recoverable(total_cost_cents, common_area_pct, recovery_cap_pct):
    """VendorBill approval waterfall (PRD §3.4)."""
    common_area_cents = floor_pct(total_cost_cents, common_area_pct)
    cap_cents = floor_pct(total_cost_cents, recovery_cap_pct)
    post_deduction = total_cost_cents - common_area_cents
    recoverable_cents = min(post_deduction, cap_cents)
    return common_area_cents, cap_cents, recoverable_cents


def largest_remainder_allocation(recoverable_cents, weighted_units):
    """Largest-remainder distribution.

    weighted_units: list of dicts with keys 'unit_id', 'weight', 'seq'.
    Returns {unit_id: charge_cents}.

    Order for remainder distribution: weight DESC, then creation seq ASC.
    """
    total_weight = sum(u["weight"] for u in weighted_units)
    result = {u["unit_id"]: 0 for u in weighted_units}
    if total_weight <= 0:
        # Zero total weight/consumption: every charge is 0; pool stays unallocated.
        return result

    rec = _to_decimal(recoverable_cents)
    tw = _to_decimal(total_weight)
    floor_shares = {}
    allocated = 0
    for u in weighted_units:
        share = int((rec * _to_decimal(u["weight"]) / tw).to_integral_value(rounding="ROUND_FLOOR"))
        floor_shares[u["unit_id"]] = share
        allocated += share

    remainder = recoverable_cents - allocated

    # Distribute remainder one cent at a time in (weight DESC, seq ASC) order.
    ordered = sorted(weighted_units, key=lambda u: (-u["weight"], u["seq"]))
    i = 0
    n = len(ordered)
    while remainder > 0 and n > 0:
        u = ordered[i % n]
        floor_shares[u["unit_id"]] += 1
        remainder -= 1
        i += 1

    return floor_shares


def admin_fee_proration(monthly_admin_fee_cents, period_start, period_end,
                        move_in_date, move_out_date):
    """Prorate the admin fee to occupied days within the period (PRD §3.7).

    All inputs that are dates are datetime.date. period bounds inclusive.
    """
    period_days = (period_end - period_start).days + 1
    occ_start = max(move_in_date, period_start)
    effective_move_out = move_out_date if move_out_date is not None else period_end
    occ_end = min(effective_move_out, period_end)
    occupied_days = (occ_end - occ_start).days + 1

    if occupied_days <= 0:
        return 0
    if occupied_days >= period_days:
        return monthly_admin_fee_cents
    # floor(fee * occupied_days / period_days)
    return int((_to_decimal(monthly_admin_fee_cents) * _to_decimal(occupied_days)
                / _to_decimal(period_days)).to_integral_value(rounding="ROUND_FLOOR"))


def late_fee(balance_due_cents):
    """Four-step fixed-order late fee (PRD §3.10).

    1. percentage base = ceil(LATE_FEE_PCT * balance)
    2. flat floor       = max(LATE_FEE_FLAT_CENTS, base)
    3. absolute cap     = min(fee, LATE_FEE_MAX_CENTS)
    4. state-law pct cap = min(fee, floor(LATE_FEE_MAX_PCT * balance))
    """
    base = int((_to_decimal(balance_due_cents) * LATE_FEE_PCT).to_integral_value(rounding="ROUND_CEILING"))
    fee = max(LATE_FEE_FLAT_CENTS, base)
    fee = min(fee, LATE_FEE_MAX_CENTS)
    state_law_cap = int((_to_decimal(balance_due_cents) * LATE_FEE_MAX_PCT).to_integral_value(rounding="ROUND_FLOOR"))
    fee = min(fee, state_law_cap)
    return fee


def recompute_statement_totals(stmt):
    """Re-derive total_due_cents and balance_due_cents (PRD §3.8)."""
    stmt["total_due_cents"] = (
        stmt["utility_charge_cents"]
        + stmt["admin_fee_cents"]
        + stmt["late_fee_cents"]
        - stmt["credit_cents"]
    )
    stmt["balance_due_cents"] = stmt["total_due_cents"] - stmt["amount_paid_cents"]
