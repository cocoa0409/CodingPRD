"""Calculation rules (PRD §3 / scaffold Table 3).

All monetary amounts are integer cents (PRD §2.8). Fractional cents from
prorations are rounded half up. Use Decimal with ROUND_HALF_UP — never float.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# Overage tier ladder constants (PRD §3.10).
TIER1_LIMIT_GB = 50
TIER1_RATE_CENTS = 50
TIER2_LIMIT_GB = 50
TIER2_RATE_CENTS = 30
TIER3_RATE_CENTS = 20
OVERAGE_CAP_CENTS = 6000

# Outage SLA threshold (PRD §3.6).
MIN_QUALIFYING_MINUTES = 240

# Promo discount thresholds (PRD §3.10).
PROMO_LOW_CENTS = 8000
PROMO_LOW_OFF_CENTS = 500
PROMO_HIGH_CENTS = 10000
PROMO_HIGH_OFF_CENTS = 1000


def round_half_up(numerator, denominator):
    """round_half_up(numerator / denominator) to whole cents (integer)."""
    if denominator == 0:
        return 0
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def overage_charge_cents(cumulative_usage_gb, plan):
    """Three-tier overage ladder (PRD §3.10).

    over_gb = max(0, cumulative_usage_gb - included_gb)  (strict: == is not over)
    Only plans with overage_policy == BILL bill overage; THROTTLE/UNLIMITED -> 0.
    """
    if plan["overage_policy"] != "BILL":
        return 0
    over_gb = max(0, cumulative_usage_gb - plan["included_gb"])
    rem = over_gb
    cost = 0
    t1 = min(rem, TIER1_LIMIT_GB)
    cost += t1 * TIER1_RATE_CENTS
    rem -= t1
    t2 = min(rem, TIER2_LIMIT_GB)
    cost += t2 * TIER2_RATE_CENTS
    rem -= t2
    cost += rem * TIER3_RATE_CENTS
    return min(cost, OVERAGE_CAP_CENTS)


def overage_estimate_cents(usage_so_far_gb, days_elapsed, cycle_days, plan):
    """Forward-looking estimate (PRD §3.10).

    projected = floor(usage_so_far / days_elapsed * cycle_days), then run the
    identical tier ladder + cap on the projected figure.
    """
    if days_elapsed <= 0:
        projected = usage_so_far_gb
    else:
        projected = math.floor(usage_so_far_gb / days_elapsed * cycle_days)
    return overage_charge_cents(projected, plan)


def outage_credit_cents(monthly_fee_cents, qualifying_minutes, cycle_minutes):
    """Outage SLA credit (PRD §3.6).

    credit = round_half_up(monthly_fee * qualifying_minutes / cycle_minutes),
    capped at one month's fee.
    """
    if cycle_minutes <= 0:
        return 0
    credit = round_half_up(monthly_fee_cents * qualifying_minutes, cycle_minutes)
    return min(credit, monthly_fee_cents)


def lease_proration_credit_cents(lease_fee_cents_per_cycle, days_remaining,
                                 cycle_days):
    """Lease proration refund (PRD §3.7).

    refund = round_half_up(lease_fee * days_remaining / cycle_days).
    """
    if cycle_days <= 0:
        return 0
    return round_half_up(lease_fee_cents_per_cycle * days_remaining, cycle_days)


def early_termination_fee_cents(plan, months_elapsed):
    """ETF decay (PRD §3.8).

    Month-to-month (contract_term_months == 0) -> 0.
    Otherwise etf_full * months_remaining / contract_term_months, half up.
    """
    term = plan["contract_term_months"]
    if term == 0:
        return 0
    months_remaining = max(0, term - months_elapsed)
    return round_half_up(plan["etf_full_cents"] * months_remaining, term)


def promo_discount_cents(subtotal_pre):
    """Promo discount keyed on subtotal_pre = plan_fee + lease_fee (PRD §3.10)."""
    if subtotal_pre >= PROMO_HIGH_CENTS:
        return PROMO_HIGH_OFF_CENTS
    if subtotal_pre >= PROMO_LOW_CENTS:
        return PROMO_LOW_OFF_CENTS
    return 0


def whole_minutes_between(start_dt, end_dt):
    """Whole minutes between two instants (floor of the second-difference / 60)."""
    delta = (end_dt - start_dt).total_seconds()
    return int(delta // 60)


def whole_days_in_window(start_dt, end_dt):
    """Whole days in a window [start, end)."""
    delta = (end_dt - start_dt).total_seconds()
    return int(delta // 86400)


def whole_days_used(start_dt, now_dt):
    """Whole days from cycle start up to now, counting the start day (PRD §3.7).

    days_used = whole days from cycle_start to now, inclusive of the start day.
    """
    delta = (now_dt - start_dt).total_seconds()
    return int(delta // 86400) + 1


def whole_months_between(start_dt, now_dt):
    """Whole months elapsed between two instants (PRD §3.8)."""
    if now_dt < start_dt:
        return 0
    months = (now_dt.year - start_dt.year) * 12 + (now_dt.month - start_dt.month)
    # Subtract one month if the day/time-of-month has not yet been reached.
    if (now_dt.day, now_dt.hour, now_dt.minute, now_dt.second, now_dt.microsecond) \
            < (start_dt.day, start_dt.hour, start_dt.minute, start_dt.second,
               start_dt.microsecond):
        months -= 1
    return max(0, months)


def merge_intervals(intervals):
    """Merge overlapping [start, end) intervals; return total covered minutes.

    Overlapping outage intervals are merged before summing so double-coverage
    of the same minute counts once (PRD §3.6).
    """
    if not intervals:
        return 0
    ivs = sorted(intervals, key=lambda p: p[0])
    merged = [list(ivs[0])]
    for s, e in ivs[1:]:
        last = merged[-1]
        if s <= last[1]:
            if e > last[1]:
                last[1] = e
        else:
            merged.append([s, e])
    total_seconds = sum((e - s).total_seconds() for s, e in merged)
    return int(total_seconds // 60)
