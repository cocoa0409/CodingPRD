"""Time-based billing, overdue penalty, and lost-conversion calculations.

All monetary arithmetic uses Decimal with ROUND_HALF_UP at 2 decimal places.
"""
import math
from decimal import Decimal
from common import to_money

OVERDUE_TIER_A_HOURLY = Decimal("5.00")   # hours 24-72 elapsed
OVERDUE_TIER_B_HOURLY = Decimal("10.00")  # hours 72-168 elapsed
LOST_DEVICE_FEE = Decimal("99.00")
LOST_THRESHOLD_HOURS = 168
OVERDUE_THRESHOLD_HOURS = 24


def _elapsed_hours(rented_at, end_time) -> int:
    elapsed_seconds = (end_time - rented_at).total_seconds()
    return math.floor(elapsed_seconds / 3600)


def _total_minutes(rented_at, end_time) -> int:
    elapsed_seconds = (end_time - rented_at).total_seconds()
    return math.floor(elapsed_seconds / 60)


def rental_fee(rental_rented_at, end_time, plan, *, final: bool, return_plan_city_code=None,
               start_city_code=None) -> Decimal:
    """Compute rental fee per PRD §3.5. Final variant adds cross_city_surcharge if cities differ."""
    total_minutes = _total_minutes(rental_rented_at, end_time)
    free_minutes = plan["free_minutes"]
    billable_minutes = max(0, total_minutes - free_minutes)
    billable_hours = math.ceil(billable_minutes / 60) if billable_minutes > 0 else 0

    hourly_rate: Decimal = plan["hourly_rate"]
    daily_cap: Decimal = plan["daily_cap"]

    if billable_hours <= 24:
        fee = min(Decimal(billable_hours) * hourly_rate, daily_cap)
    else:
        fee = daily_cap

    if final and return_plan_city_code is not None and start_city_code is not None and start_city_code != return_plan_city_code:
        fee = fee + plan["cross_city_surcharge"]

    return to_money(fee)


def overdue_penalty(rental_rented_at, end_time) -> Decimal:
    """Compute overdue penalty per PRD §3.6 tiered hourly schedule."""
    elapsed = _elapsed_hours(rental_rented_at, end_time)
    if elapsed <= OVERDUE_THRESHOLD_HOURS:
        return Decimal("0.00")
    overdue_hours = elapsed - OVERDUE_THRESHOLD_HOURS
    if overdue_hours <= 48:
        penalty = Decimal(overdue_hours) * OVERDUE_TIER_A_HOURLY
    elif overdue_hours <= 144:
        penalty = (Decimal(48) * OVERDUE_TIER_A_HOURLY) + (Decimal(overdue_hours - 48) * OVERDUE_TIER_B_HOURLY)
    else:
        penalty = (Decimal(48) * OVERDUE_TIER_A_HOURLY) + (Decimal(96) * OVERDUE_TIER_B_HOURLY)
    return to_money(penalty)


def elapsed_hours(rented_at, end_time) -> int:
    return _elapsed_hours(rented_at, end_time)
