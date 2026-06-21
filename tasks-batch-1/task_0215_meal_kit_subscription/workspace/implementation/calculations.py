"""Calculation rules (PRD §3.6, §3.7; SCAFFOLD §1.3).

All money is integer cents. Rounding is round-half-up, applied exactly once per
calculation at the single specified step.
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

import db
import timeutil

# --- constants (SCAFFOLD §1.3) ---
DIET_PREMIUM = {
    "STANDARD": 0,
    "VEGETARIAN": 0,
    "PESCATARIAN": 150,
    "LOW_CARB": 200,
    "FAMILY_FRIENDLY": 0,
}
PREMIUM_RECIPE_UPCHARGE = 400
REFERRAL_CREDIT_CAP_PER_BOX = 2000
LOYALTY_T_GOLD_MIN = 24
LOYALTY_T_SILVER_MIN = 12
PRORATION_CYCLE_DAYS = 30
REFERRAL_REWARD_CENTS = 1500
MAX_REFERRAL_REWARDS_PER_CYCLE = 3


def _round_half_up(value):
    """Round a Decimal to whole cents using round-half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _per_serving_rate(total_servings):
    if total_servings >= 16:
        return 899
    if total_servings >= 8:
        return 999
    return 1099


def _loyalty_pct(lifetime_box_count):
    if lifetime_box_count >= LOYALTY_T_GOLD_MIN:
        return Decimal("0.10")
    if lifetime_box_count >= LOYALTY_T_SILVER_MIN:
        return Decimal("0.05")
    return Decimal("0.00")


def weekly_box_charge(plan, subscription, zone, premium_slot_count,
                      credit_balance_cents, lifetime_box_count):
    """Eleven-step weekly-box charge (PRD §3.6).

    Returns (charge_cents, credit_applied_cents). Pure: no ledger mutation.
    The caller decides whether to deduct credit (FINAL variant) or not
    (PROVISIONAL variant).
    """
    # 1. total servings
    total_servings = plan["servings_per_meal"] * plan["meals_per_week"]
    # 2. per-serving rate by tier
    rate = _per_serving_rate(total_servings)
    # 3. base
    diet_premium = DIET_PREMIUM[subscription["diet_preference"]]
    base = (rate + diet_premium) * total_servings
    # 4. premium upcharge
    premium_upcharge = PREMIUM_RECIPE_UPCHARGE * premium_slot_count
    # 5. subtotal
    subtotal = base + premium_upcharge
    # 6. zone total
    zone_total = subtotal + zone["cold_pack_surcharge_cents"]
    # 7. loyalty pct (pre-increment snapshot)
    loyalty_pct = _loyalty_pct(lifetime_box_count)
    # 8. loyalty discount: round half-up ONCE here
    loyalty_discount = _round_half_up(Decimal(zone_total) * loyalty_pct)
    # 9. after loyalty
    after_loyalty = zone_total - loyalty_discount
    # 10. credit applied
    credit_applied = min(credit_balance_cents, REFERRAL_CREDIT_CAP_PER_BOX, after_loyalty)
    # 11. charge
    charge = after_loyalty - credit_applied
    return charge, credit_applied


def pause_proration_credit(monthly_addon_fee_cents, billing_cycle_day, now):
    """Unused-portion refund of the monthly add-on fee (PRD §3.6).

    days_elapsed_in_cycle = current clock date - most recent billing_cycle_day
    anchor on/before current date, clamped to [0, 30].
    unused_days = max(0, 30 - days_elapsed).
    credit = round_half_up(fee * unused_days / 30), rounded once.
    """
    cur_date = timeutil.date_of(now)
    anchor = _most_recent_anchor(cur_date, billing_cycle_day)
    days_elapsed = (cur_date - anchor).days
    if days_elapsed < 0:
        days_elapsed = 0
    if days_elapsed > PRORATION_CYCLE_DAYS:
        days_elapsed = PRORATION_CYCLE_DAYS
    unused_days = PRORATION_CYCLE_DAYS - days_elapsed
    if unused_days < 0:
        unused_days = 0
    credit = _round_half_up(
        Decimal(monthly_addon_fee_cents) * Decimal(unused_days) / Decimal(PRORATION_CYCLE_DAYS)
    )
    return credit


def _most_recent_anchor(cur_date, billing_cycle_day):
    """Most recent date on/before cur_date whose day-of-month == billing_cycle_day.

    billing_cycle_day is in [1, 28], so it exists in every month.
    """
    if cur_date.day >= billing_cycle_day:
        return cur_date.replace(day=billing_cycle_day)
    # Step back to the previous month.
    year = cur_date.year
    month = cur_date.month - 1
    if month == 0:
        month = 12
        year -= 1
    return cur_date.replace(year=year, month=month, day=billing_cycle_day)


def cutoff_at(delivery_dt, cutoff_weekday):
    """Most recent cutoff_weekday at 23:59:59.000Z strictly before delivery_date.

    Walk backward day-by-day from delivery_date - 1 day until the ISO weekday
    equals cutoff_weekday (PRD §3.6).
    """
    d = (delivery_dt - timedelta(days=1))
    # ISO weekday: Monday=1 .. Sunday=7
    while d.isoweekday() != cutoff_weekday:
        d = d - timedelta(days=1)
    return d.replace(hour=23, minute=59, second=59, microsecond=0)
