"""Calculation rules (SCAFFOLD §1.3, PRD §2.5 / §3.9 / §3.12).

All money is integer cents. Rounding is round-half-up, applied at the exact point
each calculation names (never deferred)."""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

# Constants (SCAFFOLD §1.3)
W_SEVERITY = 2
W_REACTION = 1
W_VITAL = 3
AE_HOLD_THRESHOLD = 7

PUMP_REPROCESS_MIN = 1440
TRAVEL_BUFFER_MIN = 60
LAB_DUE_DAYS = 14  # lab-due horizon in days (LAB_DUE_DAYS monitoring window)


def round_half_up(value):
    """Round a numeric value half-up to the nearest whole cent (integer)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def whole_vials(daily_dose_mg, billed_days, vial_size_mg):
    """ceil( (daily_dose_mg * billed_days) / vial_size_mg ) — whole-vial ceiling."""
    numerator = daily_dose_mg * billed_days
    # ceiling division of non-negative integers
    return -(-numerator // vial_size_mg)


def ae_severity_score(severity_grade, reaction_count, vital_instability):
    """severity_score = 2*grade + 1*reaction_count + 3*vital_instability (integer)."""
    return (W_SEVERITY * severity_grade) + (W_REACTION * reaction_count) + (W_VITAL * vital_instability)


def per_diem_line(plan, drug, billed_days):
    """rate_cents (selected by drug.therapy_category) * billed_days. Exact, no rounding."""
    rate = plan["per_diem_rate_cents"].get(drug["therapy_category"], 0)
    return rate * billed_days


def drug_line_allowed(order, drug, plan, billed_days):
    """Whole-vial ceiling BEFORE discount; round the discounted line once to whole cents."""
    billed_units = whole_vials(order["daily_dose_mg"], billed_days, drug["vial_size_mg"])
    gross_cents = billed_units * drug["awp_per_vial_cents"]
    discounted = Decimal(str(gross_cents)) * (Decimal("1") - Decimal(str(plan["awp_discount_pct"])))
    return round_half_up(discounted)


def copay_waterfall(plan, allowed_total):
    """Returns (patient_responsibility_cents, plan_paid_cents, ded_applied).
    Deductible bucket first, then coinsurance on the remainder (round half up),
    OOP cap applied last."""
    ded_applied = min(plan["deductible_remaining_cents"], allowed_total)
    after_ded = allowed_total - ded_applied
    coins_cents = round_half_up(Decimal(str(after_ded)) * Decimal(str(plan["coinsurance_pct"])))
    patient_pre_cap = ded_applied + coins_cents
    patient_responsibility = min(patient_pre_cap, plan["oop_max_remaining_cents"])
    plan_paid = allowed_total - patient_responsibility
    return patient_responsibility, plan_paid, ded_applied


def pump_conflict(new_delivery, new_retrieval, existing_delivery, existing_retrieval):
    """Trailing-only buffer on existing END, half-open. Conflict when:
        new.delivery_at < (existing.retrieval_at + buffer) AND new.retrieval_at > existing.delivery_at
    Start exactly at existing.retrieval_at + buffer is allowed (no conflict)."""
    buffered_end = existing_retrieval + timedelta(minutes=PUMP_REPROCESS_MIN)
    return new_delivery < buffered_end and new_retrieval > existing_delivery


def nurse_conflict(new_start, new_duration, existing_start, existing_duration):
    """Symmetric travel buffer on both ends, closed endpoints. Conflict when:
        new.start_at < (existing.start_at + existing.duration + buffer) AND
        (new.start_at + new.duration + buffer) > existing.start_at"""
    buf = timedelta(minutes=TRAVEL_BUFFER_MIN)
    existing_end_buffered = existing_start + timedelta(minutes=existing_duration) + buf
    new_end_buffered = new_start + timedelta(minutes=new_duration) + buf
    return new_start < existing_end_buffered and new_end_buffered > existing_start


def lab_window(order_start_date):
    """Returns (lo, hi) inclusive trough monitoring window: [start_date, start_date + LAB_DUE_DAYS days]."""
    return order_start_date, order_start_date + timedelta(days=LAB_DUE_DAYS)
