"""Calculation rules from SCAFFOLD.yaml §1.3 / PRD §3."""

from datetime import date, timedelta
import math


def business_days_between(submitted_date: date, shoot_start_date: date, holidays: list) -> int:
    """Count dates t where submitted_date < t <= shoot_start_date,
    weekday(t) not in {Sat, Sun}, t not in holidays.
    Half-open: submission date excluded, shoot date included if business day."""
    holiday_set = set(holidays) if holidays else set()
    count = 0
    d = submitted_date + timedelta(days=1)
    while d <= shoot_start_date:
        if d.weekday() < 5 and d.isoformat() not in holiday_set:
            count += 1
        d += timedelta(days=1)
    return count


def business_days_in_window(start_date: date, end_date: date, holidays: list) -> int:
    """Count business days in [start_date, end_date] inclusive."""
    holiday_set = set(holidays) if holidays else set()
    count = 0
    d = start_date
    while d <= end_date:
        if d.weekday() < 5 and d.isoformat() not in holiday_set:
            count += 1
        d += timedelta(days=1)
    return count


def calendar_days_in_window(start_date: date, end_date: date) -> int:
    """Count calendar days in [start_date, end_date] inclusive."""
    return (end_date - start_date).days + 1


def permit_fee(base_fee_cents: int, per_day_fee_cents: int, per_lane_fee_cents: int,
               days: int, closed_lanes: int, cast_size: int,
               large_cast_threshold: int, large_cast_multiplier_bps: int) -> int:
    """permit_fee calc. days computed by caller (business-day model at submit).
    Single floor at final multiplication."""
    subtotal = base_fee_cents + days * per_day_fee_cents + days * closed_lanes * per_lane_fee_cents
    if cast_size > large_cast_threshold:
        return (subtotal * large_cast_multiplier_bps) // 10000
    return subtotal


def notification_adequacy(calendar_days_before_shoot: int, radius_ft_used: int,
                          notification_lead_calendar_days: int, notification_radius_ft: int) -> bool:
    """Both comparisons >= (inclusive boundary)."""
    return (calendar_days_before_shoot >= notification_lead_calendar_days
            and radius_ft_used >= notification_radius_ft)


def monitors_required(shoot_hours_per_day: int, closed_lanes: int,
                      cast_size: int, police_monitor_lane_threshold: int,
                      large_cast_threshold: int) -> int:
    """monitors_required calc."""
    base = math.ceil(shoot_hours_per_day / 8) if shoot_hours_per_day > 0 else 0
    lane_extra = 1 if closed_lanes >= police_monitor_lane_threshold else 0
    cast_extra = 1 if cast_size > large_cast_threshold else 0
    return base + lane_extra + cast_extra


def deposit_required(deposit_floor_cents: int, agreed_day_rate_cents: int, shoot_days: int) -> int:
    """deposit_required calc. Pinned rounding: rate * days first, then * 50, then floor(/100)."""
    risk_amount = (agreed_day_rate_cents * shoot_days * 50) // 100
    return max(deposit_floor_cents, risk_amount)


def deposit_waterfall(held: int, released: int, awarded: int):
    """deposit_waterfall calc. Returns (claimed_delta, released_delta)."""
    actual_award = min(awarded, held - released)
    claimed_delta = actual_award
    released_delta = held - released - actual_award
    return claimed_delta, released_delta


def shoot_day_compliance(overtime_minutes: int, monitors_confirmed: int,
                         monitors_required: int, complaints: list) -> str:
    """shoot_day_compliance strict variant: ALL complaints count (including RESOLVED).
    complaints is a list of dicts with 'severity' key."""
    violations = 0
    if overtime_minutes > 0:
        violations += 1
    if monitors_confirmed < monitors_required:
        violations += 1
    for c in complaints:
        sev = c.get("severity", "")
        if sev in ("HIGH", "CRITICAL"):
            violations += 2
        elif sev == "MEDIUM":
            violations += 1
    if violations >= 2:
        return "VIOLATION"
    elif violations == 1:
        return "DEGRADED"
    return "COMPLIANT"
