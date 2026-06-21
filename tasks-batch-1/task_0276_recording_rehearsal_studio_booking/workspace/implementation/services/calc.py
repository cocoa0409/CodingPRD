"""Calculation rules (PRD §3.2-§3.7, scaffold §1.3).

All money is integer cents. Fractional cents are rounded half-up. Where a
formula rounds hours/blocks/rental-days up to a whole unit, the ceiling is
applied to the time quantity FIRST, then multiplied by the rate (PRD §2.6).
"""
import math
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round a numeric value half-up to the nearest whole integer (cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def duration_hours(start_dt, end_dt):
    """Scheduled duration in hours as an exact fraction."""
    return (end_dt - start_dt).total_seconds() / 3600.0


def ceil_to_quarter_hour(hours):
    """Round a number of hours UP to the next quarter hour (PRD §3.5)."""
    # hours*4 rounded up to a whole number, divided by 4.
    quarters = math.ceil(hours * 4 - 1e-9)
    return quarters / 4.0


def base_charge_cents(booking_kind, start_dt, end_dt, room):
    """Room time charge (PRD §3.2 / base_charge calc)."""
    dur = duration_hours(start_dt, end_dt)
    if booking_kind == "HOURLY":
        billable_hours = math.ceil(dur - 1e-9)
        return billable_hours * room["hourly_rate_cents"]
    # BLOCK or LOCKOUT
    block_hours = room["block_hours"]
    blocks = math.ceil(dur / block_hours - 1e-9)
    return blocks * room["block_rate_cents"]


def deposit_due_cents(base_charge, deposit_pct):
    """Deposit = round_half_up(base_charge * deposit_pct) (PRD §3.2)."""
    return round_half_up(Decimal(str(base_charge)) * Decimal(str(deposit_pct)))


def gear_rental_days(start_dt, end_dt):
    """ceil(duration_hours / 24), minimum 1 (PRD §3.6 / gear_rental_charge)."""
    dur = duration_hours(start_dt, end_dt)
    days = math.ceil(dur / 24.0 - 1e-9)
    return max(1, days)


def gear_charge_cents(units, rental_days, daily_rate_cents):
    return units * rental_days * daily_rate_cents


def scheduled_hours(start_dt, end_dt):
    """Booking scheduled duration rounded UP to next quarter hour (PRD §3.5)."""
    return ceil_to_quarter_hour(duration_hours(start_dt, end_dt))


def engineering_estimate_cents(sched_hours, engineer_rate_cents):
    """estimate = round_half_up(scheduled_hours * rate) (PRD §3.5)."""
    return round_half_up(Decimal(str(sched_hours)) * Decimal(str(engineer_rate_cents)))


def overtime_hours_quarter(overage_minutes):
    """Overtime portion in hours, rounded up to next quarter hour (PRD §3.5)."""
    overtime_hours = overage_minutes / 60.0
    return ceil_to_quarter_hour(overtime_hours)


def engineering_final_cents(sched_hours, overtime_qh, engineer_rate_cents):
    """final = round_half_up(billed_hours * rate); billed = sched + overtime_qh."""
    billed_hours = sched_hours + overtime_qh
    charge = round_half_up(Decimal(str(billed_hours)) * Decimal(str(engineer_rate_cents)))
    return billed_hours, charge


def billable_overage_minutes(actual_end_dt, end_dt, grace_minutes):
    """raw overage minutes floored at 0, minus grace, floored at 0 (PRD §3.4)."""
    raw_secs = (actual_end_dt - end_dt).total_seconds()
    raw_minutes = int(raw_secs // 60)
    raw_over = max(0, raw_minutes)
    overage = max(0, raw_over - grace_minutes)
    return overage


def room_overtime_surcharge_cents(overage_minutes, room_hourly_rate_cents, overtime_multiplier):
    """round_half_up((overage/60) * room_rate * multiplier) (PRD §3.4)."""
    value = (Decimal(overage_minutes) / Decimal(60)) * Decimal(str(room_hourly_rate_cents)) * Decimal(str(overtime_multiplier))
    return round_half_up(value)


def engineer_overtime_surcharge_cents(overage_minutes, engineer_rate_cents):
    """round_half_up(ceil_to_quarter((overage/60)) * engineer_rate) (PRD §3.4)."""
    qh = overtime_hours_quarter(overage_minutes)
    return round_half_up(Decimal(str(qh)) * Decimal(str(engineer_rate_cents)))


def cancellation_fee_cents(base_charge, late_cancel_fee_pct):
    """round_half_up(base_charge * late_cancel_fee_pct) (PRD §3.7)."""
    return round_half_up(Decimal(str(base_charge)) * Decimal(str(late_cancel_fee_pct)))
