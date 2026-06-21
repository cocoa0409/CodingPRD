"""Financial calculations — integer cents throughout.

Uses Decimal for any fractional-cent step. Rounding rules per PRD 2.5 / 3.5 / 3.6:
  - mileage division: round half up
  - airfare advance-purchase 80% reduction: truncate toward zero (floor)
  - per-diem 75% first/last day proration: round half up PER DAY then sum
"""
from decimal import Decimal, ROUND_HALF_UP

from common import date_diff_days

FIRST_LAST_DAY_FACTOR = Decimal("0.75")
OOP_BUDGET_MULTIPLE = 2


def round_half_up(value):
    """Round a Decimal half up (away from zero on the .5 boundary) to whole cents."""
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_to_int(value):
    """Truncate toward zero to a whole integer (floor for non-negative)."""
    return int(Decimal(value).to_integral_value(rounding="ROUND_DOWN"))


# -------------------------------------------------------------------------
# Per-line reimbursement
# -------------------------------------------------------------------------

def flight_line(claimed, cabin_class, scheduled_hours, advance_days, policy):
    """FLIGHT line: returns (reimbursable_cents, in_policy)."""
    in_policy = True
    if cabin_class == "BUSINESS":
        if scheduled_hours < policy["business_class_min_hours"]:
            in_policy = False
        cap = claimed  # business fares not capped when in-policy
    else:  # ECONOMY
        cap = policy["max_economy_fare_cents"]
        if advance_days < policy["advance_purchase_days"]:
            # 80% of the economy cap, truncated toward zero
            cap = floor_to_int(Decimal(cap) * Decimal("0.80"))
    reimbursable = min(claimed, cap)
    if claimed > cap:
        in_policy = False
    return reimbursable, in_policy


def cdw_line(claimed, rental_days, policy):
    """RENTAL_CDW line: returns (reimbursable_cents, in_policy)."""
    cap = policy["cdw_daily_cap_cents"] * rental_days
    reimbursable = min(claimed, cap)
    in_policy = claimed <= cap
    return reimbursable, in_policy


def mileage_line(miles, policy):
    """MILEAGE line: returns (reimbursable_cents, in_policy). Always in-policy."""
    reimbursable = round_half_up(Decimal(miles * policy["mileage_rate_milli_cents"]) / Decimal(1000))
    return reimbursable, True


def lodging_line(claimed, check_in_date, check_out_date, lodging_cap_cents):
    """LODGING line: returns (reimbursable_cents, in_policy)."""
    nights = date_diff_days(check_out_date, check_in_date)
    cap = lodging_cap_cents * nights
    reimbursable = min(claimed, cap)
    in_policy = claimed <= cap
    return reimbursable, in_policy


# -------------------------------------------------------------------------
# Per-diem / meal reimbursement
# -------------------------------------------------------------------------

def per_diem_total(rate, trip_days):
    """GSA M&IE per-diem: 75% first & last day, full middle days.

    Round half up PER DAY, THEN sum (order is pinned).
    """
    if trip_days == 1:
        return round_half_up(Decimal(rate) * FIRST_LAST_DAY_FACTOR)
    total = round_half_up(Decimal(rate) * FIRST_LAST_DAY_FACTOR)  # first day
    total += round_half_up(Decimal(rate) * FIRST_LAST_DAY_FACTOR)  # last day
    total += rate * (trip_days - 2)  # full middle days (already whole cents)
    return total


def meal_reimbursable(report, trip, meal_lines, mie_cents):
    """Dual-variant meal reimbursement at report level.

    PER_DIEM: ignore claimed amounts, use flat per-diem total.
    ITEMIZED: min(sum of MEAL claimed amounts, per-diem total).
    """
    trip_days = date_diff_days(trip["end_date"], trip["start_date"]) + 1
    pd_total = per_diem_total(mie_cents, trip_days)
    if report["per_diem_method"] == "PER_DIEM":
        return pd_total
    # ITEMIZED
    actual = sum(line["claimed_amount_cents"] for line in meal_lines)
    return min(actual, pd_total)


def report_total(meal_reimbursable_cents, lines):
    """Total = meal portion + sum of non-REJECTED, non-MEAL line reimbursables."""
    total = meal_reimbursable_cents
    for line in lines:
        if line["status"] == "REJECTED":
            continue
        if line["line_type"] == "MEAL":
            continue
        total += line["reimbursable_amount_cents"]
    return total


# -------------------------------------------------------------------------
# Trip out-of-policy flag
# -------------------------------------------------------------------------

def trip_requires_oop(trip, lodging_cap_cents, mie_cents):
    """requires_oop = budget > 2 * (lodging_cap + mie) * trip_nights.

    trip_nights = date_diff_days(end_date, start_date)  (no inclusive +1).
    Strictly greater -> out-of-policy; exactly equal -> in-policy.
    """
    trip_nights = date_diff_days(trip["end_date"], trip["start_date"])
    baseline = OOP_BUDGET_MULTIPLE * (lodging_cap_cents + mie_cents) * trip_nights
    return trip["budget_total_cents"] > baseline
