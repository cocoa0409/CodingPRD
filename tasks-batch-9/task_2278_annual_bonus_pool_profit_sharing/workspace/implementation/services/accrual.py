"""calc provisional_pool_funding — the forecast (provisional) funding variant."""

from decimal import Decimal

import db
from services import calc

EMPLOYED_STATUSES = ("ACTIVE", "ON_LEAVE")


def forecast_blended_and_multiplier(plan, forecast_company_pct):
    pools = db.plan_pools(plan["id"])
    certified = [p for p in pools
                 if p["calibration_status"] == "SCORECARD_CERTIFIED"]
    if certified:
        forecast_bu_pct = calc.bu_weighted_achievement(
            pools, plan["total_target_cents"])
    else:
        forecast_bu_pct = Decimal("100.00")
    blended = calc.blended_achievement(
        plan["company_weight_pct"], plan["business_unit_weight_pct"],
        plan["individual_weight_pct"], forecast_company_pct, forecast_bu_pct)
    return blended, calc.funding_curve_multiplier(blended)


def target_basis(plan):
    """(provisional_target_basis, target_basis_cents)."""
    awards = db.plan_awards(plan["id"])
    if awards:
        total = sum(a["prorated_target_cents"] for a in awards
                    if a["eligibility_status"] != "INELIGIBLE_MIN_SERVICE")
        return "AWARD_PRORATED", total

    total = 0
    for participant in db.plan_participants(plan["id"]):
        if participant["employment_status"] not in EMPLOYED_STATUSES:
            continue
        target = db.target_for_level(plan["id"], participant["current_job_level"])
        if target is None:
            continue
        total += calc.unprorated_participant_target_cents(
            participant["current_base_salary_cents"], target["target_bonus_pct"])
    return "PARTICIPANT_UNPRORATED", total


def value_period(plan, period):
    """Write the provisional + burden figures onto `period` (pinned order)."""
    basis, basis_cents = target_basis(plan)
    _blended, multiplier = forecast_blended_and_multiplier(
        plan, period["forecast_company_achievement_pct"])

    period["provisional_target_basis"] = basis
    period["provisional_pool_cents"] = calc.provisional_pool_cents(
        basis_cents, multiplier)

    # 1. elapsed days, inclusive of both endpoints
    elapsed = (db.as_date(period["period_end"])
               - db.as_date(plan["plan_period_start"])).days + 1
    period["elapsed_days"] = elapsed

    # 2. cumulative target
    cumulative = calc.cumulative_accrual_target_cents(
        period["provisional_pool_cents"], elapsed)
    period["cumulative_accrual_target_cents"] = cumulative

    # 3. movement against the ledger already posted (may be negative)
    movement = cumulative - plan["accrued_base_cents"]
    period["period_accrual_cents"] = movement

    # 4. burden: the tier is keyed on the PRE-burden cumulative figure
    rate = calc.burden_rate_pct(cumulative)
    period["burden_rate_pct"] = rate
    period["burden_cents"] = calc.burden_cents(movement, rate)
    period["total_period_cents"] = movement + period["burden_cents"]
