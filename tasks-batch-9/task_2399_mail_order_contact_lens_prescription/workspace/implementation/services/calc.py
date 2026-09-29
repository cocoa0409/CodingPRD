"""Calculations: business-hour arithmetic, pricing, deviation index, proration,
reimbursement money steps and auto-reorder cadence.

All money is integer cents; every division/percentage rounds half up (PRD 2.6),
except the torn-lens cap which floors.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ------------------------------------------------------------------- constants
FREE_SHIPPING_THRESHOLD_CENTS = 5000
STANDARD_SHIPPING_CENTS = 695

WEIGHT_BASE_CURVE = 4
WEIGHT_DIAMETER = 2
WEIGHT_SPHERE_PER_EYE = 1
AUTO_APPROVE_MAX_INDEX = Decimal("0.50")
CONSENT_MAX_INDEX = Decimal("1.00")

BUSINESS_DAY_START_HOUR = 8
BUSINESS_DAY_END_HOUR = 17
DIRECTORY_VERIFIED_BUSINESS_HOURS = 8
SELF_REPORTED_BUSINESS_HOURS = 12
CONTACT_COOLDOWN_BUSINESS_HOURS = 4

MAX_VERIFICATION_ROUNDS = 3
MAX_PENDING_REQUESTS_PER_PRESCRIBER = 3

TORN_LENS_CAP_RATE = Decimal("0.20")

FEE_TIER_1_MAX_CENTS = 5000
FEE_TIER_1_CENTS = 0
FEE_TIER_2_MAX_CENTS = 15000
FEE_TIER_2_CENTS = 250
FEE_TIER_3_CENTS = 500

MIN_CADENCE_DAYS = 14
REORDER_LEAD_TIME_DAYS = 5
DAYS_PER_LENS = {"DAILY_DISPOSABLE": 1, "BIWEEKLY": 14, "MONTHLY": 30}
MAX_CONSECUTIVE_SKIPS = 2
RUN_HOUR_UTC = 8

ONE = Decimal(1)


def round_half_up(value):
    return int(Decimal(value).quantize(ONE, rounding=ROUND_HALF_UP))


def hundredths(value):
    """h(v) from the deviation calculation: v * 100 rounded half up to an integer."""
    return int((Decimal(value) * 100).quantize(ONE, rounding=ROUND_HALF_UP))


# ------------------------------------------------------- business-hour arithmetic


def _day_start(moment):
    return moment.replace(hour=BUSINESS_DAY_START_HOUR, minute=0, second=0, microsecond=0)


def _day_end(moment):
    return moment.replace(hour=BUSINESS_DAY_END_HOUR, minute=0, second=0, microsecond=0)


def _next_business_day_start(moment):
    cursor = _day_start(moment + timedelta(days=1))
    while cursor.weekday() >= 5:
        cursor = cursor + timedelta(days=1)
    return cursor


def advance_business_hours(start, budget_hours):
    """PRD section 2.5 business-hour walk."""
    cursor = start.astimezone(timezone.utc)
    # Step 2: normalise before any budget is consumed.
    while True:
        if cursor.weekday() >= 5:
            cursor = _day_start(cursor + timedelta(days=1))
            continue
        if cursor < _day_start(cursor):
            cursor = _day_start(cursor)
            break
        if cursor >= _day_end(cursor):
            cursor = _next_business_day_start(cursor)
            continue
        break
    # Step 3: consume the budget.
    remaining = Decimal(str(budget_hours))
    while remaining > 0:
        available = Decimal((_day_end(cursor) - cursor).total_seconds()) / Decimal(3600)
        if remaining <= available:
            cursor = cursor + timedelta(seconds=float(remaining * 3600))
            remaining = Decimal(0)
        else:
            remaining -= available
            cursor = _next_business_day_start(cursor)
    return cursor


def passive_deadline(sent_at, directory_verified):
    budget = DIRECTORY_VERIFIED_BUSINESS_HOURS if directory_verified else SELF_REPORTED_BUSINESS_HOURS
    return advance_business_hours(sent_at, budget)


def cooldown_end(sent_at):
    return advance_business_hours(sent_at, CONTACT_COOLDOWN_BUSINESS_HOURS)


# ------------------------------------------------------------------ order pricing


def price_order(unit_price_cents, total_boxes):
    subtotal = unit_price_cents * total_boxes
    shipping = 0 if subtotal >= FREE_SHIPPING_THRESHOLD_CENTS else STANDARD_SHIPPING_CENTS
    return subtotal, shipping, subtotal + shipping


# -------------------------------------------------------- parameter deviation index


def snap_sphere(sphere, step):
    """Nearest multiple of `step`; exact ties resolve away from zero."""
    value_h = hundredths(sphere)
    step_h = hundredths(step)
    if step_h <= 0:
        return Decimal(sphere).quantize(Decimal("0.01"))
    magnitude = abs(value_h)
    multiples, remainder = divmod(magnitude, step_h)
    if remainder * 2 >= step_h:
        multiples += 1
    snapped = multiples * step_h
    if value_h < 0:
        snapped = -snapped
    return (Decimal(snapped) / Decimal(100)).quantize(Decimal("0.01"))


def deviation_index(prescription, product):
    """Returns (index, fulfilled_od_sphere, fulfilled_os_sphere)."""
    od_fulfilled = snap_sphere(prescription["od_sphere"], product["sphere_step"])
    os_fulfilled = snap_sphere(prescription["os_sphere"], product["sphere_step"])
    raw = (
        WEIGHT_BASE_CURVE * abs(hundredths(prescription["base_curve"]) - hundredths(product["base_curve"]))
        + WEIGHT_DIAMETER * abs(hundredths(prescription["diameter"]) - hundredths(product["diameter"]))
        + WEIGHT_SPHERE_PER_EYE * abs(hundredths(prescription["od_sphere"]) - hundredths(od_fulfilled))
        + WEIGHT_SPHERE_PER_EYE * abs(hundredths(prescription["os_sphere"]) - hundredths(os_fulfilled))
    )
    index = (Decimal(raw) / Decimal(100)).quantize(Decimal("0.01"))
    return index, od_fulfilled, os_fulfilled


# ------------------------------------------------------------- return settlement

SETTLEMENT_MODE_BY_REASON = {
    "PRESCRIPTION_CHANGE": "PER_BOX_ROUNDED",
    "WRONG_PARAMETER": "POOLED_ROUNDED",
    "TORN_LENS": "NO_PRORATION",
}


def settlement_channel_for(reason):
    return "STORE_CREDIT" if reason == "TORN_LENS" else "CASH_REFUND"


def return_settlement(order, reason, unopened_boxes, opened_box_used_counts, torn_lens_count):
    unit = order["unit_price_cents"]
    lpb = order["lenses_per_box_at_capture"]
    mode = SETTLEMENT_MODE_BY_REASON[reason]
    opened = list(opened_box_used_counts or [])
    if mode == "NO_PRORATION":
        candidate = round_half_up(Decimal((torn_lens_count or 0) * unit) / Decimal(lpb))
        cap = int((Decimal(order["total_cents"]) * TORN_LENS_CAP_RATE).to_integral_value(rounding="ROUND_FLOOR"))
        cents = min(candidate, cap)
        return mode, cents, settlement_channel_for(reason)

    unopened_component = (unopened_boxes or 0) * unit
    if mode == "PER_BOX_ROUNDED":
        opened_component = 0
        for used in opened:
            opened_component += round_half_up(Decimal(unit * (lpb - used)) / Decimal(lpb))
    else:  # POOLED_ROUNDED
        pooled_unused = sum((lpb - used) for used in opened)
        opened_component = round_half_up(Decimal(unit * pooled_unused) / Decimal(lpb))
    return mode, unopened_component + opened_component, settlement_channel_for(reason)


# --------------------------------------------------------- reimbursement claim money


def processing_fee(pre_fee_subtotal_cents):
    if pre_fee_subtotal_cents <= FEE_TIER_1_MAX_CENTS:
        return FEE_TIER_1_CENTS
    if pre_fee_subtotal_cents <= FEE_TIER_2_MAX_CENTS:
        return FEE_TIER_2_CENTS
    return FEE_TIER_3_CENTS


def claim_money(order, plan, refund_offset_cents, allowance_used_cents):
    gross = order["subtotal_cents"] + (order["shipping_cents"] if plan["covers_shipping"] else 0)
    base_eligible = max(0, gross - refund_offset_cents)
    remaining_allowance = max(0, plan["annual_allowance_cents"] - allowance_used_cents)
    applied_allowance = min(base_eligible, remaining_allowance)
    coinsurance = round_half_up(Decimal(base_eligible - applied_allowance) * Decimal(plan["coinsurance_rate"]))
    pre_fee_subtotal = applied_allowance + coinsurance
    fee = processing_fee(pre_fee_subtotal)
    reimbursable = max(0, pre_fee_subtotal - fee)
    return {
        "refund_offset_cents": refund_offset_cents,
        "base_eligible_cents": base_eligible,
        "applied_allowance_cents": applied_allowance,
        "coinsurance_cents": coinsurance,
        "pre_fee_subtotal_cents": pre_fee_subtotal,
        "processing_fee_cents": fee,
        "reimbursable_cents": reimbursable,
    }


# ------------------------------------------------------------- auto-reorder cadence


def cadence_days_for(product, boxes_per_run, cadence_basis, observed_days_per_box):
    if cadence_basis == "USAGE_ADJUSTED":
        supply_days = boxes_per_run * (observed_days_per_box or 0)
    else:
        supply_days = boxes_per_run * product["lenses_per_box"] * DAYS_PER_LENS[product["wear_schedule"]]
    return max(MIN_CADENCE_DAYS, supply_days - REORDER_LEAD_TIME_DAYS)


def run_instant(anchor_date, cadence_days):
    target = anchor_date + timedelta(days=cadence_days)
    return datetime(target.year, target.month, target.day, RUN_HOUR_UTC, 0, 0, tzinfo=timezone.utc)


def plan_year_window(anchor_month_day, reference_date):
    month, day = anchor_month_day.split("-")
    month, day = int(month), int(day)
    try:
        candidate = reference_date.replace(month=month, day=day)
    except ValueError:
        candidate = reference_date.replace(month=month, day=1)
    if candidate > reference_date:
        candidate = candidate.replace(year=candidate.year - 1)
    try:
        end = candidate.replace(year=candidate.year + 1)
    except ValueError:
        end = candidate.replace(year=candidate.year + 1, day=1)
    return candidate, end
