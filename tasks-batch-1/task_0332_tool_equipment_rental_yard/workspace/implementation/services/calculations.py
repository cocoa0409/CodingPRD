"""Charge calculations (PRD §3.8, SCAFFOLD §1.3).

All monetary amounts are integer cents (PRD §2.6). The only fractional
intermediate is the late fee (late_fee_multiplier may be fractional), which is
rounded half up to whole cents.
"""
from decimal import Decimal, ROUND_HALF_UP

from .common import billed_days, parse_date


# Delivery fee flat amounts keyed by category (PRD §3.4 / SCAFFOLD §1.3).
DELIVERY_FEE_BY_CATEGORY_CENTS = {
    "HAND_TOOL": 0,
    "POWER_TOOL": 2500,
    "HEAVY_EQUIPMENT": 12000,
}


def rental_charge_cents(days, rate_card):
    """Tiered rental charge over a given billed-day count (PRD §3.8).

    Greedy decompose into 28-day, then 7-day, then loose days. Then apply the
    best-rate guard in PINNED order: day->week cap first, then week->4week cap.
    Exact integer-cent arithmetic.
    """
    daily = rate_card["daily_rate_cents"]
    weekly = rate_card["weekly_rate_cents"]
    four_week = rate_card["four_week_rate_cents"]

    four_week_blocks = days // 28
    rem_after_4w = days % 28
    week_blocks = rem_after_4w // 7
    loose_days = rem_after_4w % 7

    # --- best-rate guard (PINNED ORDER) -----------------------------------
    # 1. day -> week cap: if loose days priced at daily exceed a whole week,
    #    charge one week instead of those loose days.
    if loose_days * daily > weekly:
        week_blocks += 1
        loose_days = 0

    # 2. week -> 4week cap: after the day->week adjustment, if the weeks within
    #    the current 28-day remainder priced at weekly exceed a 4-week block,
    #    charge one 4-week block instead.
    if week_blocks * weekly > four_week:
        four_week_blocks += 1
        week_blocks = 0

    return (four_week_blocks * four_week
            + week_blocks * weekly
            + loose_days * daily)


def estimate_rental_cents(reservation_start, reservation_end, rate_card):
    """Estimate variant: full planned interval [rental_start_date, rental_end_date]."""
    days = billed_days(reservation_start, reservation_end)
    return rental_charge_cents(days, rate_card)


def final_interval_days(actual_start_date, actual_return_date, scheduled_end_date):
    """Final variant interval: [actual_start, min(actual_return, scheduled_end)].

    Overdue days are NOT billed at the rental rate (billed under late fee).
    Inclusive day count, always >= 1.
    """
    end = min(parse_date(actual_return_date), parse_date(scheduled_end_date))
    end_str = end.isoformat()
    return billed_days(actual_start_date, end_str)


def final_rental_cents(actual_start_date, actual_return_date, scheduled_end_date, rate_card):
    days = final_interval_days(actual_start_date, actual_return_date, scheduled_end_date)
    return rental_charge_cents(days, rate_card)


def late_fee_cents(actual_return_date, scheduled_end_date, rate_card):
    """Late fee = round_half_up(overdue_days * daily_rate * multiplier) (PRD §3.8).

    overdue_days = max(0, (actual_return - scheduled_end).days). Returning ON the
    scheduled end date => 0 overdue => no late fee.
    """
    overdue_days = (parse_date(actual_return_date) - parse_date(scheduled_end_date)).days
    if overdue_days < 0:
        overdue_days = 0
    if overdue_days == 0:
        return 0
    daily = rate_card["daily_rate_cents"]
    multiplier = rate_card["late_fee_multiplier"]
    raw = Decimal(overdue_days) * Decimal(daily) * Decimal(str(multiplier))
    return int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fuel_refill_cents(return_fuel_level_liters, fuel_capacity_liters, rate_card):
    """Fuel refill charge (PRD §3.8).

    Dispatch fuel level == capacity (dispatched full). missing = max(0,
    capacity - return_level), capped at capacity. charge = capped * per_liter.
    """
    missing = fuel_capacity_liters - return_fuel_level_liters
    if missing < 0:
        missing = 0
    capped = min(missing, fuel_capacity_liters)
    return capped * rate_card["fuel_refill_cents_per_liter"]


def net_damage_cents(damage_assessed_cents, damage_waiver_opted):
    """Net damage (PRD §3.8): 0 when waiver opted, else gross."""
    if damage_waiver_opted:
        return 0
    return damage_assessed_cents


def estimated_waiver_cents(damage_waiver_opted, planned_days, rate_card):
    """Estimated waiver amount at confirm (PRD §3.4)."""
    if not damage_waiver_opted:
        return 0
    return rate_card["damage_waiver_daily_cents"] * planned_days


def delivery_fee_cents(fulfillment_method, category):
    """Flat delivery fee keyed by category for DELIVERY, else 0 (PRD §3.4)."""
    if fulfillment_method != "DELIVERY":
        return 0
    return DELIVERY_FEE_BY_CATEGORY_CENTS[category]


def final_total_cents(final_rental, waiver_cents, late_fee, fuel_refill,
                      cleaning_cents, net_damage, deposit_refund):
    """Final total in PINNED 1..7 order (PRD §3.8 / SCAFFOLD §1.3).

    final_total = rental + waiver + late_fee + fuel_refill + cleaning + net_damage
                  - deposit_refund.
    """
    return (final_rental + waiver_cents + late_fee + fuel_refill
            + cleaning_cents + net_damage - deposit_refund)
