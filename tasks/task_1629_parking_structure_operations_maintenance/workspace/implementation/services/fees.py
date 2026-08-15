"""Calculations per PRD 3 / scaffold calculations table.

Implements: transient_fee_calculation, monthly_proration, monthly_pool_availability,
waitlist_promotion ranking, shift_expected_cash, variance_threshold_classification,
capital_reserve_ledger levy, ev_charger_utilization, event_pool_allocation,
structural_condition_index, event_cancellation_fee.
"""
import calendar
import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from db import parse_iso

# Constants pinned by the scaffold
SHORTAGE_REVIEW_CENTS = 2000
OVERAGE_REVIEW_CENTS = 5000
VARIANCE_HIGH_CENTS = 10000
COMP_CAP_PER_SHIFT_CENTS = 5000
UTIL_WINDOW_DAYS = 28
MIN_UTIL_PCT = Decimal("5.0")
SLIDING_THRESHOLD_HOURS = 48


def round_half_up_int(value):
    """Round a Decimal to integer cents, half-up."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round a Decimal to two decimal places, half-up; returned as float for JSON."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def whole_minutes(delta):
    """Durations discard sub-minute remainders (PRD 2.4)."""
    return int(delta.total_seconds() // 60)


# ---------------------------------------------------------------------------
# transient_fee_calculation (PRD 3.2)
# ---------------------------------------------------------------------------

def _segment_fee(segment_minutes, rate):
    hours = math.ceil(segment_minutes / 60) if segment_minutes > 0 else 0
    fee = rate["first_hour_cents"] + max(0, hours - 1) * rate["additional_hour_cents"]
    return min(fee, rate["daily_max_cents"])


def compute_fee(session, as_of):
    """Rate a session at `as_of` against the schedule pinned at entry."""
    rate = db.rate_schedules.get(session["rate_schedule_id"])
    if rate is None:
        return 0
    mode = session["fee_mode"]
    if mode == "MONTHLY":
        return 0
    if mode == "EVENT_FLAT":
        return int(rate["event_flat_cents"])

    entry = parse_iso(session["entry_at"])

    if mode == "LOST_TICKET":
        # distinct calendar dates touched by [entry_at, as_of]; minimum 1
        days = (as_of.date() - entry.date()).days + 1
        return int(rate["lost_ticket_daily_cents"]) * max(1, days)

    # STANDARD
    elapsed_min = whole_minutes(as_of - entry)
    if elapsed_min <= 0:
        elapsed_min = max(0, elapsed_min)
    if elapsed_min <= rate["grace_minutes"]:
        return 0

    total = 0
    if rate["cap_mode"] == "ROLLING_24H":
        window = timedelta(hours=24)
        start = entry
        while start < as_of:
            end = min(start + window, as_of)
            total += _segment_fee(whole_minutes(end - start), rate)
            start = end
    else:  # CALENDAR_DAY — split at each (UTC) midnight
        start = entry
        while start < as_of:
            next_midnight = parse_iso(
                (start.date() + timedelta(days=1)).isoformat() + "T00:00:00Z"
            )
            end = min(next_midnight, as_of)
            total += _segment_fee(whole_minutes(end - start), rate)
            start = end
    return total


# ---------------------------------------------------------------------------
# monthly_proration (PRD 3.4) — per-component round-half-up, then sum
# ---------------------------------------------------------------------------

def compute_first_invoice(agreement, activated_at):
    days_in_month = calendar.monthrange(activated_at.year, activated_at.month)[1]
    remaining_days = days_in_month - activated_at.day + 1
    rent = round_half_up_int(
        Decimal(agreement["monthly_rate_cents"]) * remaining_days / days_in_month
    )
    ev = round_half_up_int(
        Decimal(agreement["ev_surcharge_cents"]) * remaining_days / days_in_month
    )
    return rent + ev


# ---------------------------------------------------------------------------
# monthly_pool_availability counters (PRD 3.4)
# ---------------------------------------------------------------------------

def pool_counts(facility_id):
    allocated = 0  # ACTIVE + SUSPENDED
    approved = 0
    for a in db.monthly_agreements.values():
        if a["facility_id"] != facility_id:
            continue
        if a["agreement_status"] in ("ACTIVE", "SUSPENDED"):
            allocated += 1
        elif a["agreement_status"] == "APPROVED":
            approved += 1
    return allocated, approved


# ---------------------------------------------------------------------------
# shift_expected_cash (PRD 3.5) — waterfall: float, cash-in, refunds, paid-outs, over-rings
# ---------------------------------------------------------------------------

def compute_expected_cash(shift):
    total = shift["opening_float_cents"]
    for s in db.parking_sessions.values():
        if s.get("paid_in_shift_id") != shift["id"]:
            continue
        if s.get("tender_type") != "CASH":
            continue
        if s["billing_state"] in ("SETTLED", "REFUNDED") and s.get("settled_fee_cents") is not None:
            total += s["settled_fee_cents"]
        if s["billing_state"] == "REFUNDED" and s.get("refunded_cents") is not None:
            total -= s["refunded_cents"]
    total -= shift.get("paid_out_cents", 0)
    total += shift.get("over_ring_cents", 0)
    return total


def refresh_shift_expected(shift):
    """Recompute and store expected_cash_cents unless the shift is frozen (RECONCILED)."""
    if shift["shift_status"] == "RECONCILED":
        return
    shift["expected_cash_cents"] = compute_expected_cash(shift)


# ---------------------------------------------------------------------------
# variance_threshold_classification (PRD 3.5) — inclusive thresholds
# ---------------------------------------------------------------------------

def classify_variance(variance_cents):
    if variance_cents <= -SHORTAGE_REVIEW_CENTS or variance_cents >= OVERAGE_REVIEW_CENTS:
        return "VARIANCE_REVIEW"
    return "SUBMITTED"


def variance_incident_severity(variance_cents):
    return "HIGH" if abs(variance_cents) >= VARIANCE_HIGH_CENTS else "MEDIUM"


# ---------------------------------------------------------------------------
# structural_condition_index (PRD 3.6)
# ---------------------------------------------------------------------------

def compute_condition(load_bearing, waterproofing, surface):
    index = round_half_up_int(
        Decimal(20) * (
            Decimal("0.5") * load_bearing
            + Decimal("0.3") * waterproofing
            + Decimal("0.2") * surface
        )
    )
    if load_bearing <= 2 or index < 40:
        klass = "CRITICAL"
    elif index < 70:
        klass = "FAIR"
    else:
        klass = "SOUND"
    return index, klass


# ---------------------------------------------------------------------------
# event_pool_allocation (PRD 3.9) — strict half-open overlap
# ---------------------------------------------------------------------------

def windows_overlap(a_start, a_end, b_start, b_end):
    """Strict half-open overlap: touching endpoints do NOT overlap."""
    return a_start < b_end and b_start < a_end


def event_pool_charge(candidate, facility_id):
    charge = candidate["presale_allocation"]
    c_start = parse_iso(candidate["start_at"])
    c_end = parse_iso(candidate["end_at"])
    for other in db.event_bookings.values():
        if other["id"] == candidate["id"]:
            continue
        if other["facility_id"] != facility_id:
            continue
        if other["booking_status"] not in ("CONFIRMED", "ACTIVE"):
            continue
        if windows_overlap(c_start, c_end, parse_iso(other["start_at"]), parse_iso(other["end_at"])):
            charge += other["presale_allocation"]
    return charge


# ---------------------------------------------------------------------------
# event_cancellation_fee (PRD 3.9)
# ---------------------------------------------------------------------------

def compute_cancellation_fee(event, now):
    if event["booking_status"] == "REQUESTED":
        fee = 0
    elif event["cancellation_policy"] == "FORFEIT_DEPOSIT":
        fee = event["deposit_cents"]
    else:  # SLIDING_NOTICE
        notice_minutes = whole_minutes(parse_iso(event["start_at"]) - now)
        if notice_minutes < SLIDING_THRESHOLD_HOURS * 60:
            fee = event["deposit_cents"]
        else:
            fee = round_half_up_int(Decimal(event["deposit_cents"]) / 2)
    return fee, event["deposit_cents"] - fee


# ---------------------------------------------------------------------------
# ev_charger_utilization (PRD 3.8)
# ---------------------------------------------------------------------------

def recompute_charger_utilization(charger, run_time, business_date):
    window_floor = parse_iso(
        (business_date - timedelta(days=UTIL_WINDOW_DAYS)).isoformat() + "T00:00:00Z"
    )
    commissioned = parse_iso(charger["commissioned_at"])
    window_start = max(commissioned, window_floor)
    available_minutes = whole_minutes(run_time - window_start)

    if available_minutes <= 0:
        session_pct = 0.0
        energy_pct = 0.0
    else:
        sum_min = 0
        sum_kwh = Decimal(0)
        for s in db.charging_sessions.values():
            if s["charger_id"] != charger["id"]:
                continue
            if s["session_status"] != "COMPLETED":
                continue
            ended = parse_iso(s["ended_at"])
            if not (window_start <= ended <= run_time):
                continue
            sum_min += whole_minutes(ended - parse_iso(s["started_at"]))
            sum_kwh += Decimal(str(s["kwh_delivered"]))
        session_pct = round_half_up_2dp(
            Decimal(100) * Decimal(sum_min) / Decimal(available_minutes)
        )
        available_hours = Decimal(available_minutes) / Decimal(60)
        deliverable = Decimal(charger["max_kw"]) * available_hours
        energy_pct = round_half_up_2dp(Decimal(100) * sum_kwh / deliverable)

    charger["utilization_session_pct"] = session_pct
    charger["utilization_energy_pct"] = energy_pct
    if Decimal(str(session_pct)) < MIN_UTIL_PCT:
        charger["low_util_run_count"] = charger.get("low_util_run_count", 0) + 1
    else:
        charger["low_util_run_count"] = 0
    if charger["low_util_run_count"] >= 2:
        charger["utilization_review_flag"] = True
    db.touch(charger)
