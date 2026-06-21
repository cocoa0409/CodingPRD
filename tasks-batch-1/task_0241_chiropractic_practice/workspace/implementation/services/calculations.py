"""Calculation rules (PRD §3.8, scaffold §1.3).

All money is integer cents. Every fraction multiplication is rounded half-up to
whole cents before use (PRD §2.8).
"""
from decimal import Decimal, ROUND_HALF_UP

import db

# ---- Constants (scaffold §1.3 no_show_fee + cap) ----
FIRST_TIER_MAX_STRIKES = 2
SECOND_TIER_MAX_STRIKES = 4
FIRST_TIER_FEE_CENTS = 2500
SECOND_TIER_FEE_CENTS = 5000
THIRD_TIER_FEE_CENTS = 7500
LATE_CANCEL_MULTIPLIER = Decimal("0.5")
DISMISSAL_STRIKE_THRESHOLD = 5
LATE_CANCEL_WINDOW_HOURS = 24
REGRESSION_SEVERITY_THRESHOLD = 6

CAP_COUNTING_VISIT_TYPES = {"ADJUSTMENT", "THERAPY", "RE_EXAM"}


def round_half_up(value):
    """Round a numeric value to the nearest whole cent, halves up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def mul_round(cents, fraction):
    """cents * fraction, rounded half-up to whole cents."""
    return round_half_up(Decimal(int(cents)) * Decimal(str(fraction)))


def active_fee_schedule(visit_type):
    """The single ACTIVE FeeSchedule for a visit_type, or None."""
    for fs in db.fee_schedules.values():
        if fs["visit_type"] == visit_type and fs["status"] == "ACTIVE":
            return fs
    return None


def _calendar_month_key(scheduled_start):
    """(year, month) extracted from an ISO 8601 UTC instant string."""
    # scheduled_start is stored canonically as 'YYYY-MM-DDTHH:MM:SS.fffZ'
    return scheduled_start[:4], scheduled_start[5:7]


def wellness_adjustment_ordinal(patient_id, appt):
    """1-based ordinal of `appt` among this patient's ATTENDED ADJUSTMENT
    appointments in the same calendar month (by scheduled_start UTC), including
    itself, ordered scheduled_start ASC then created_at ASC (PRD §3.8).
    """
    year, month = _calendar_month_key(appt["scheduled_start"])
    siblings = []
    for a in db.appointments.values():
        if a["patient_id"] != patient_id:
            continue
        if a["visit_type"] != "ADJUSTMENT":
            continue
        if a["attendance_status"] != "ATTENDED":
            continue
        ay, am = _calendar_month_key(a["scheduled_start"])
        if (ay, am) != (year, month):
            continue
        siblings.append(a)
    # Ensure the current appointment is counted even if its status is being set
    # to ATTENDED within the same transaction (caller marks it ATTENDED first).
    if appt["id"] not in {a["id"] for a in siblings}:
        siblings.append(appt)
    siblings.sort(key=lambda a: (a["scheduled_start"], a["created_at"], a.get("_seq", 0)))
    for idx, a in enumerate(siblings):
        if a["id"] == appt["id"]:
            return idx + 1
    return len(siblings)


def patient_responsibility(patient, appt):
    """Compute (patient_responsibility_cents, insurance_paid_cents,
    applied_to_deductible_cents) for a completing appointment (PRD §3.8).

    applied_to_deductible_cents is returned so adjudication can later bump the
    policy's deductible_met_cents.
    """
    fee = active_fee_schedule(appt["visit_type"])
    cash_rate = fee["cash_rate_cents"] if fee else 0
    mode = patient["payer_mode"]

    if mode == "CASH":
        return cash_rate, 0, 0

    if mode == "WELLNESS":
        if appt["visit_type"] == "ADJUSTMENT":
            plan = db.wellness_plans.get(patient.get("wellness_plan_id"))
            included = plan["included_adjustments_per_month"] if plan else 0
            ordinal = wellness_adjustment_ordinal(patient["id"], appt)
            if ordinal <= included:
                return 0, 0, 0
            disc_pct = plan["overage_discount_pct"] if plan else 0
            disc = mul_round(cash_rate, disc_pct)
            return cash_rate - disc, 0, 0
        return cash_rate, 0, 0

    # INSURANCE
    policy = db.insurance_policies.get(appt.get("insurance_policy_id"))
    allowed = policy["allowed_amount_cents"] if policy else 0
    if policy:
        remaining_deductible = max(0, policy["deductible_total_cents"] - policy["deductible_met_cents"])
    else:
        remaining_deductible = 0
    applied_to_deductible = min(allowed, remaining_deductible)
    after_deductible = allowed - applied_to_deductible
    coins_pct = policy["coinsurance_pct"] if policy else 0
    coins = mul_round(after_deductible, coins_pct)
    pr = applied_to_deductible + coins
    insurance_paid = allowed - pr
    return pr, insurance_paid, applied_to_deductible


def no_show_fee(strikes_after, transition):
    """Tiered no-show fee by post-increment strike count (PRD §3.8).

    transition is 'NO_SHOW' or 'LATE_CANCEL'.
    """
    if strikes_after <= FIRST_TIER_MAX_STRIKES:
        base = FIRST_TIER_FEE_CENTS
    elif strikes_after <= SECOND_TIER_MAX_STRIKES:
        base = SECOND_TIER_FEE_CENTS
    else:
        base = THIRD_TIER_FEE_CENTS
    if transition == "LATE_CANCEL":
        return mul_round(base, LATE_CANCEL_MULTIPLIER)
    return base
