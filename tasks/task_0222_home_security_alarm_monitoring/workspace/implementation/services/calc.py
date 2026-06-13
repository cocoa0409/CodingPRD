"""Calculation rules (scaffold §1.3 / PRD §2.6, §3.2, §3.3, §3.8).

All money is integer cents. Division/scaling rounds half up. We use Decimal with
ROUND_HALF_UP for any fractional-cent step.
"""
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# ----- constants -----
CYCLE_DAYS = 30

# false_alarm_fine
FREE_ALLOWANCE = 2
WARN_BAND = 3
WARN_FINE_CENTS = 5000
ESCALATED_FINE_CENTS = 10000
NO_PERMIT_SURCHARGE_CENTS = 7500

# dispatch_fee
POLICE_DISPATCH_FEE_CENTS = 2500
FIRE_DISPATCH_FEE_CENTS = 4000
MEDICAL_DISPATCH_FEE_CENTS = 4000

# signal_routing / temporal
SIGNAL_DEBOUNCE_SECONDS = 60
TEST_MODE_WINDOW_MINUTES = 120


def test_mode_window():
    return timedelta(minutes=TEST_MODE_WINDOW_MINUTES)

# permit_fee
BASE_PERMIT_FEE_CENTS = 5000
COMMERCIAL_UPLIFT_CENTS = 3000
LATE_PCT_PER_PERIOD = Decimal("0.20")
LATE_PERIOD_DAYS = 30
LATE_CAP_CENTS = 4000

# communicator_health
CHECKIN_MAX_MINUTES = 360
SIGNAL_MIN_DBM = -85
BATTERY_MIN_PCT = 20

# early_termination_fee
ETF_PER_REMAINING_MONTH_CENTS = 2000


def round_half_up(value):
    """Round a numeric/Decimal value to the nearest integer, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# communicator_health
# ---------------------------------------------------------------------------
def communicator_health(last_checkin_minutes_ago, cellular_signal_dbm, backup_battery_pct):
    if last_checkin_minutes_ago > CHECKIN_MAX_MINUTES:
        return "OFFLINE"
    signal_ok = cellular_signal_dbm >= SIGNAL_MIN_DBM
    battery_ok = backup_battery_pct >= BATTERY_MIN_PCT
    if signal_ok and battery_ok:
        return "HEALTHY"
    return "DEGRADED"


# ---------------------------------------------------------------------------
# signal_routing
# ---------------------------------------------------------------------------
def routed_service_for(signal_type):
    if signal_type in ("BURGLARY", "PANIC"):
        return "POLICE"
    if signal_type == "FIRE":
        return "FIRE"
    if signal_type == "MEDICAL":
        return "MEDICAL"
    return None


# ---------------------------------------------------------------------------
# dispatch_fee
# ---------------------------------------------------------------------------
def dispatch_fee(service, police_dispatch_included):
    if service == "POLICE":
        return 0 if police_dispatch_included else POLICE_DISPATCH_FEE_CENTS
    if service == "FIRE":
        return FIRE_DISPATCH_FEE_CENTS
    if service == "MEDICAL":
        return MEDICAL_DISPATCH_FEE_CENTS
    return 0


# ---------------------------------------------------------------------------
# permit_fee
# ---------------------------------------------------------------------------
def permit_fee(premises_type, filed_days_late):
    base = BASE_PERMIT_FEE_CENTS
    if premises_type == "COMMERCIAL":
        base += COMMERCIAL_UPLIFT_CENTS
    if filed_days_late == 0:
        late_penalty = 0
    else:
        periods = math.ceil(filed_days_late / LATE_PERIOD_DAYS)
        raw = Decimal(BASE_PERMIT_FEE_CENTS) * LATE_PCT_PER_PERIOD * Decimal(periods)
        late_penalty = round_half_up(raw)
        if late_penalty > LATE_CAP_CENTS:
            late_penalty = LATE_CAP_CENTS
    return base + late_penalty


# ---------------------------------------------------------------------------
# early_termination_fee
# ---------------------------------------------------------------------------
def early_termination_fee(contract_start_utc, contract_term_months, request_clock):
    elapsed_seconds = (request_clock - contract_start_utc).total_seconds()
    elapsed_months = int(elapsed_seconds // (CYCLE_DAYS * 86400))
    remaining_months = max(0, contract_term_months - elapsed_months)
    if remaining_months == 0:
        return 0
    return remaining_months * ETF_PER_REMAINING_MONTH_CENTS


# ---------------------------------------------------------------------------
# false_alarm_fine base
# ---------------------------------------------------------------------------
def false_alarm_fine_base(ordinal):
    if ordinal <= FREE_ALLOWANCE:
        return 0
    if ordinal <= FREE_ALLOWANCE + WARN_BAND:  # 3,4,5
        return WARN_FINE_CENTS
    return ESCALATED_FINE_CENTS


# ---------------------------------------------------------------------------
# monitoring_proration — day-by-day, round-then-sum (FINAL/chronological)
# ---------------------------------------------------------------------------
def monitoring_proration(cycle_anchor_utc, eval_clock, current_tier, segments, plan_fee_by_tier):
    """Sum of per-day charges across elapsed whole days.

    segments: list of {at: datetime, tier: str} plan-change boundaries (sorted asc).
    The tier in effect at 00:00 UTC of day d is the most recent segment boundary
    on or before that instant, else current_tier (the tier at the anchor).
    plan_fee_by_tier: callable tier -> monthly_fee_cents.
    """
    if cycle_anchor_utc is None:
        return 0
    total_seconds = (eval_clock - cycle_anchor_utc).total_seconds()
    if total_seconds <= 0:
        return 0
    elapsed_days = int(total_seconds // 86400)
    if elapsed_days > CYCLE_DAYS:
        elapsed_days = CYCLE_DAYS

    total = 0
    for d in range(elapsed_days):
        # start instant of day d
        day_start = cycle_anchor_utc.timestamp() + d * 86400
        tier = current_tier
        for seg in segments:
            if seg["at"].timestamp() <= day_start:
                tier = seg["tier"]
            else:
                break
        fee = plan_fee_by_tier(tier)
        if fee is None:
            fee = 0
        daily = round_half_up(Decimal(fee) / Decimal(CYCLE_DAYS))
        total += daily
    return total
