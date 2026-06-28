"""Calculation rules (SCAFFOLD 1.3 / PRD 2.7, 3.7, 3.8, 3.9, 3.11)."""
from util import add_months, days_in_interval, round_half_up, round_half_up_frac

# ---- constants ----
SIGNAL_WEIGHT = {
    "MANUAL_BUTTON": 40,
    "FALL_DETECTED": 60,
    "BATTERY_CRITICAL": 20,
    "PERIODIC_CHECKIN_MISSED": 50,
}
FALL_BONUS = 30
BATTERY_BONUS = 25
ELEVATED_CUTOFF = 50
CRITICAL_CUTOFF = 80

GOOD_CUTOFF = 40
LOW_CUTOFF = 20

REPLACEMENT_COST_CENTS = {
    "PENDANT": 8000,
    "WRISTBAND": 9000,
    "MOBILE_GPS": 18000,
    "HOME_BASE": 12000,
}
GRADE_C_FRACTION = 0.5

HOLD_GAP_DAYS = 7


def battery_health_class(battery_pct):
    """PRD 3.5: >=40 GOOD; >=20 (<40) LOW; <20 CRITICAL. Inclusive lower bounds."""
    if battery_pct >= GOOD_CUTOFF:
        return "GOOD"
    elif battery_pct >= LOW_CUTOFF:
        return "LOW"
    return "CRITICAL"


def device_test_result(signal_ok, reported_battery_pct):
    """PRD 3.5: signal failure dominates; battery < 20 -> FAIL_BATTERY; 20 PASSes."""
    if not signal_ok:
        return "FAIL_SIGNAL"
    elif reported_battery_pct < LOW_CUTOFF:
        return "FAIL_BATTERY"
    return "PASS"


def alarm_priority_score(signal_type, fall_detection_enabled, battery_health):
    """PRD 3.8: weighted score -> ROUTINE/ELEVATED/CRITICAL with inclusive cutoffs."""
    base = SIGNAL_WEIGHT[signal_type]
    fall_bonus = FALL_BONUS if (fall_detection_enabled and signal_type == "FALL_DETECTED") else 0
    battery_bonus = BATTERY_BONUS if battery_health == "CRITICAL" else 0
    score = base + fall_bonus + battery_bonus
    if score >= CRITICAL_CUTOFF:
        return "CRITICAL"
    elif score >= ELEVATED_CUTOFF:
        return "ELEVATED"
    return "ROUTINE"


def sla_breach_check(agent_assigned_at, signal_received_at, response_sla_seconds):
    """PRD 3.9: breach only when elapsed whole-seconds STRICTLY > sla. Equality not a breach."""
    elapsed_seconds = int((agent_assigned_at - signal_received_at).total_seconds())
    return elapsed_seconds > response_sla_seconds


def prorated_cancellation_refund(variant, monthly_cents, paid_through_at, now):
    """PRD 3.7 prorated_cancellation_refund.

    STANDARD (was ACTIVE): refund = 0.
    IMMEDIATE (was SUSPENDED): per-day rate rounded half-up FIRST, then * unused_days.
    """
    if variant == "STANDARD":
        return 0
    # IMMEDIATE
    cycle_start = add_months(paid_through_at, -1)
    cycle_total_days = days_in_interval(cycle_start, paid_through_at)
    if cycle_total_days <= 0:
        return 0
    unused_days = days_in_interval(now, paid_through_at)
    per_day_cents = round_half_up(monthly_cents, cycle_total_days)
    return per_day_cents * unused_days


def equipment_damage_fee(variant, device_type):
    """PRD 3.11: DAMAGED (grade C) = 50% replacement rounded half-up; UNRETURNED = full."""
    base = REPLACEMENT_COST_CENTS[device_type]
    if variant == "DAMAGED":
        return round_half_up_frac(base, GRADE_C_FRACTION)
    elif variant == "UNRETURNED":
        return base
    return 0
