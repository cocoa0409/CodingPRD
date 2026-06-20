"""Calculation rules from PRD §2.7, §3.7, §3.8 and SCAFFOLD calculations table.
All monetary amounts are whole cents; round_half_up; round-per-component."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from services.common import days_in_month


def round_half_up(numerator, denominator):
    """round_half_up(numerator / denominator) to whole cents (PRD §2.7)."""
    q = Decimal(numerator) / Decimal(denominator)
    return int(q.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_value(value):
    """Round a (possibly fractional) Decimal/number to whole cents, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def covered_days_in_month(service_month_dt, eff_dt, disenroll_dt):
    """Count calendar days d in service_month such that
    eff_dt <= d AND (disenroll_dt is None OR d < disenroll_dt).
    Half-open interval [effective, disenroll). PRD §3.7."""
    year = service_month_dt.year
    month = service_month_dt.month
    dim = days_in_month(year, month)
    eff_d = eff_dt.date() if eff_dt is not None else None
    dis_d = disenroll_dt.date() if disenroll_dt is not None else None
    count = 0
    for day in range(1, dim + 1):
        d = date(year, month, day)
        if eff_d is not None and d < eff_d:
            continue
        if dis_d is not None and d >= dis_d:
            continue
        count += 1
    return count, dim


def capitation_amount(program, participant, proration_mode, covered_days, days_in_mo):
    """Compute the three component shares and total (PRD §3.7 / calc
    capitation_amount). Fixed order: bases -> factor -> round each -> sum."""
    medicare_base = program["medicare_monthly_rate_cents"]
    if participant["dual_eligible"]:
        medicaid_base = program["medicaid_monthly_rate_cents"]
        supplement_base = 0
    else:
        medicaid_base = 0
        supplement_base = (
            program["medicaid_monthly_rate_cents"]
            + program["medicare_only_supplement_cents"]
        )

    if proration_mode == "FULL_MONTH":
        # factor = 1 — round of an integer base is the base
        medicare_share = round_half_up(medicare_base, 1)
        medicaid_share = round_half_up(medicaid_base, 1)
        supplement = round_half_up(supplement_base, 1)
    else:  # DAILY: factor = covered_days / days_in_month
        medicare_share = round_half_up(medicare_base * covered_days, days_in_mo)
        medicaid_share = round_half_up(medicaid_base * covered_days, days_in_mo)
        supplement = round_half_up(supplement_base * covered_days, days_in_mo)

    total = medicare_share + medicaid_share + supplement
    return {
        "medicare_share_cents": medicare_share,
        "medicaid_share_cents": medicaid_share,
        "supplement_cents": supplement,
        "total_billed_cents": total,
    }


def lock_in_penalty(kind, requested_effective_dt, lock_in_end_dt,
                    medicare_monthly_rate_cents, lock_in_days):
    """PRD §3.8 lock-in penalty. Boundary: finalize ON the end date => 0 (>=)."""
    if kind != "VOLUNTARY":
        return 0
    finalize_d = requested_effective_dt.date()
    end_d = lock_in_end_dt.date()
    if finalize_d >= end_d:
        return 0
    remaining_days = (end_d - finalize_d).days  # whole calendar days, > 0
    if lock_in_days == 0:
        return 0
    return round_half_up(medicare_monthly_rate_cents * remaining_days, lock_in_days)


# Ancillary meal/activity charge constants (calc ancillary_meal_charge)
MEAL_CHARGE_CENTS = 850
ACTIVITY_BONUS_CENTS = 200


def ancillary_day_charge(meals_provided, activities_count):
    """Per-completed-day ancillary charge (PRD §3.7). Activity bonus is flat per
    day when activities_count > 0 — NOT multiplied by activity count."""
    charge = meals_provided * MEAL_CHARGE_CENTS
    if activities_count > 0:
        charge += ACTIVITY_BONUS_CENTS
    return charge


def add_days(dt, n):
    return dt + timedelta(days=n)
