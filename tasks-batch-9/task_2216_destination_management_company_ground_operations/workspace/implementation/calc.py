"""Calculation rules (PRD sections 2.6, 3.6, 3.7, 3.8, 3.9)."""

import math
from decimal import Decimal, ROUND_HALF_UP

from store import clock_now, minutes_between, plus_days, whole_days_between

# ---- constants pinned by the PRD -----------------------------------------
ATTRITION_FLOOR_PCT = Decimal("0.85")

MIN_CALL_OUT_MINUTES = 240
OT_THRESHOLD_MINUTES = 480
OT_MULTIPLIER = Decimal("1.5")

VARIANCE_TOLERANCE_PCT = Decimal("0.10")

FEE_TIER_1_CEILING = 500000
FEE_TIER_2_CEILING = 2000000
FEE_PCT_TIER_1 = Decimal("0.12")
FEE_PCT_TIER_2 = Decimal("0.09")
FEE_PCT_TIER_3 = Decimal("0.07")

CREDENTIAL_EXPIRING_WINDOW_DAYS = 14

MAX_NEGOTIATION_ROUNDS = 3

STAFF_CHECKIN_LEAD_MINUTES = 60
MANIFEST_CHECKIN_LEAD_MINUTES = 120

MARKUP_PCT_MIN = Decimal("0.05")
MARKUP_PCT_MAX = Decimal("0.35")


def dec(value):
    """Exact Decimal for a JSON number without float contamination."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places) if places else Decimal(1)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def cents(value):
    return int(round_half_up(value))


# --------------------------------------------------------------------------
# element_billable_headcount
# --------------------------------------------------------------------------

def billable_headcount_estimate(element):
    return max(int(element["planned_headcount"]), int(element["guaranteed_headcount"]))


def billable_headcount_final(guaranteed_headcount, actual_headcount, line_kind="DELIVERY"):
    if line_kind == "CANCELLATION_PENALTY":
        return 0
    guaranteed = int(guaranteed_headcount or 0)
    actual = int(actual_headcount or 0)
    attrition_floor = int(math.ceil(dec(guaranteed) * ATTRITION_FLOOR_PCT))
    return max(attrition_floor, actual)


# --------------------------------------------------------------------------
# staff_labor_cost
# --------------------------------------------------------------------------

def staff_labor_cost(minutes, pay_rate_cents_per_hour):
    """Two-leg rate ladder; each leg rounded half up, then summed."""
    minutes = int(minutes or 0)
    if minutes <= 0:
        return 0
    rate = dec(pay_rate_cents_per_hour)
    billable_minutes = max(minutes, MIN_CALL_OUT_MINUTES)
    regular_minutes = min(billable_minutes, OT_THRESHOLD_MINUTES)
    ot_minutes = max(0, billable_minutes - OT_THRESHOLD_MINUTES)
    regular_cents = round_half_up(dec(regular_minutes) / Decimal(60) * rate)
    ot_cents = round_half_up(dec(ot_minutes) / Decimal(60) * rate * OT_MULTIPLIER)
    return int(regular_cents + ot_cents)


def planned_minutes(assignment):
    return minutes_between(assignment["starts_at"], assignment["ends_at"])


def actual_minutes(assignment):
    if assignment.get("check_in_at") is None or assignment.get("completed_at") is None:
        return 0
    return minutes_between(assignment["check_in_at"], assignment["completed_at"])


# --------------------------------------------------------------------------
# reconciliation_line_amounts
# --------------------------------------------------------------------------

def markup_for(supplier_cost_cents, markup_pct):
    return cents(dec(supplier_cost_cents) * dec(markup_pct))


def variance_pct(actual_headcount, guaranteed_headcount, line_kind="DELIVERY"):
    if line_kind != "DELIVERY":
        return Decimal("0")
    guaranteed = int(guaranteed_headcount or 0)
    if guaranteed <= 0:
        return Decimal("0")
    actual = int(actual_headcount or 0)
    raw = dec(abs(actual - guaranteed)) / dec(guaranteed)
    return round_half_up(raw, 4)


# --------------------------------------------------------------------------
# program_client_total
# --------------------------------------------------------------------------

def fee_pct_for_base(base_cents):
    if base_cents < FEE_TIER_1_CEILING:
        return FEE_PCT_TIER_1
    if base_cents < FEE_TIER_2_CEILING:
        return FEE_PCT_TIER_2
    return FEE_PCT_TIER_3


def program_client_total(subtotal_cents, markup_total_cents):
    """Six-step pinned waterfall; returns (base, fee_pct, fee, total)."""
    base_cents = int(subtotal_cents) + int(markup_total_cents)
    fee_pct = fee_pct_for_base(base_cents)
    management_fee_cents = cents(dec(base_cents) * fee_pct)
    total_cents = base_cents + management_fee_cents
    return base_cents, fee_pct, management_fee_cents, total_cents


# --------------------------------------------------------------------------
# cancellation_penalty
# --------------------------------------------------------------------------

def cancellation_pct(days_to_service, cancellation_tier):
    if cancellation_tier == "STRICT":
        if days_to_service >= 45:
            return Decimal("0.10")
        if days_to_service >= 30:
            return Decimal("0.35")
        if days_to_service >= 8:
            return Decimal("0.75")
        return Decimal("1.00")
    if days_to_service >= 30:
        return Decimal("0.00")
    if days_to_service >= 15:
        return Decimal("0.25")
    if days_to_service >= 7:
        return Decimal("0.50")
    return Decimal("1.00")


def cancellation_penalty(element, cancellation_tier):
    days_to_service = whole_days_between(clock_now(), element["starts_at"])
    pct = cancellation_pct(days_to_service, cancellation_tier)
    return cents(dec(element["planned_headcount"]) * dec(element["per_person_cost_cents"]) * pct)


# --------------------------------------------------------------------------
# settlement_net_payable
# --------------------------------------------------------------------------

def settlement_waterfall(ordered_lines, deposit_paid_cents, gross_cents):
    remaining = int(deposit_paid_cents or 0)
    for line in ordered_lines:
        applied = min(remaining, int(line["supplier_cost_cents"]))
        remaining -= applied
    deposit_applied_cents = int(deposit_paid_cents or 0) - remaining
    net_payable_cents = max(0, int(gross_cents) - deposit_applied_cents)
    overpayment_credit_cents = remaining
    return deposit_applied_cents, net_payable_cents, overpayment_credit_cents


# --------------------------------------------------------------------------
# staff_credential_status
# --------------------------------------------------------------------------

def credential_status(staff_member):
    now = clock_now()
    earliest = min(staff_member["badge_expires_on"], staff_member["first_aid_expires_on"])
    if earliest < now:
        return "EXPIRED"
    if earliest <= plus_days(now, CREDENTIAL_EXPIRING_WINDOW_DAYS):
        return "EXPIRING"
    return "VALID"
