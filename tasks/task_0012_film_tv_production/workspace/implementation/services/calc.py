"""Calculations: cast commit, crew payroll, residual budget."""
from decimal import Decimal, ROUND_HALF_UP
from math import ceil
from db import store


CAP_BY_TIER = {
    "PRINCIPAL": 60,
    "SUPPORTING": 30,
    "FEATURED_BACKGROUND": 10,
}
MINUTES_PER_SHOOT_DAY = 480

# Crew payroll constants
OT_TIER_BREAK = 5
OT_FIRST_MULT = Decimal("1.50")
OT_SECOND_MULT = Decimal("1.75")


def round_half_up_cents(value: Decimal) -> int:
    """Round Decimal value (in cents) half up to nearest integer cent."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def cast_commit_estimate(production_id, role, *, variant="at_sign_time") -> int:
    """Compute the projected cast commitment in cents.

    at_sign_time: scenes with status in {BREAKDOWN, SCHEDULED, RESCHEDULING} only.
    at_offer_time: ALL scenes regardless of status.
    """
    if variant == "at_sign_time":
        valid_statuses = {"BREAKDOWN", "SCHEDULED", "RESCHEDULING"}
    else:
        valid_statuses = None  # all
    total_days = 0
    role_id = role["id"]
    for scene in store.scenes.values():
        if scene["production_id"] != production_id:
            continue
        if role_id not in (scene.get("required_actor_role_ids") or []):
            continue
        if valid_statuses is not None and scene["status"] not in valid_statuses:
            continue
        days = ceil(scene["planned_duration_minutes"] / MINUTES_PER_SHOOT_DAY)
        total_days += days
    cap = CAP_BY_TIER.get(role["union_tier"], 0)
    capped = min(total_days, cap)
    return capped * role["day_rate_cents"]


def crew_payroll(day_rate_cents: int, scheduled_days: int, actual_days: int,
                 *, variant="per_component_rounding") -> int:
    """Compute payroll in cents.

    per_component_rounding (authoritative):
        round each OT component separately, then sum.
    total_then_round (forecast/display):
        sum components in fractional cents first, round once at the end.
    """
    base_days = min(actual_days, scheduled_days)
    overtime_days = max(0, actual_days - scheduled_days)
    base_pay_cents = base_days * day_rate_cents

    ot_first = min(overtime_days, OT_TIER_BREAK)
    ot_second = max(0, overtime_days - OT_TIER_BREAK)

    ot_first_raw = Decimal(ot_first) * Decimal(day_rate_cents) * OT_FIRST_MULT
    ot_second_raw = Decimal(ot_second) * Decimal(day_rate_cents) * OT_SECOND_MULT

    if variant == "per_component_rounding":
        ot_first_cents = round_half_up_cents(ot_first_raw)
        ot_second_cents = round_half_up_cents(ot_second_raw)
        return base_pay_cents + ot_first_cents + ot_second_cents
    # total_then_round:
    total = Decimal(base_pay_cents) + ot_first_raw + ot_second_raw
    return round_half_up_cents(total)


def residual_budget(production, *, variant="final_at_wrapped") -> int:
    """Compute residual_cents.

    provisional_at_wrap_pending: total_budget - actual - committed (forecast)
    final_at_wrapped: same formula; at this point all committed_cents must be 0.
    """
    cats = [c for c in store.budget_categories.values() if c["production_id"] == production["id"]]
    actual_sum = sum(c.get("actual_cents", 0) for c in cats)
    committed_sum = sum(c.get("committed_cents", 0) for c in cats)
    return production["total_budget_cents"] - actual_sum - committed_sum
