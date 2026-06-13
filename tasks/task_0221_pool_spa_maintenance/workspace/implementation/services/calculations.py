"""Calculation rules (scaffold §1.3 / PRD §3.5, §3.9). All money is integer
cents; rounding happens at most once at the very end, round-half-up. Decimal is
used for any fractional intermediate so float drift never corrupts a cent."""
import math
from decimal import ROUND_HALF_UP, Decimal

# ---- dosing_recommendation constants (PRD §3.5) ----
FC_TARGET = {"CHLORINE": 3.0, "SALTWATER": 3.0, "BROMINE_SPA": 4.0}
DOSE_PER_PPM_PER_10K = {"CHLORINE": 14.0, "SALTWATER": 20.0, "BROMINE_SPA": 11.0}
ALK_DOSE_PER_PPM_PER_10K = 1.5
PH_PENALTY = 1.25
TA_TARGET = 100.0

# ---- final_visit_bill constants (PRD §3.5) ----
RECOVERY_SURCHARGE_CENTS = 4500
GREEN_TIER1_CENTS = 12000
GREEN_TIER2_CENTS = 18000
GREEN_TIER3_CENTS = 26000

# ---- repair_total constants (PRD §3.9) ----
LABOR_RATE_PER_HOUR_CENTS = 9000
SEVERITY_MULT = {"MINOR": "1.0", "MAJOR": "1.15", "CRITICAL": "1.35"}
TAX_RATE = "0.07"


def _round_half_up_1dp(value):
    """Round a Decimal to one decimal place, round-half-up; return float."""
    q = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(q)


def _round_half_up_int(value):
    """Round a Decimal to an integer (cents), round-half-up; return int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dosing_recommendation(water_type, volume_gallons, free_chlorine_ppm, ph, total_alkalinity_ppm):
    """recommended_dose_grams: sum-then-round-once to 1 decimal, round-half-up.

    Uses Decimal throughout so the single final round is exact at the .x5 boundary.
    """
    target_fc = Decimal(str(FC_TARGET[water_type]))
    dose_const = Decimal(str(DOSE_PER_PPM_PER_10K[water_type]))
    vol_factor = Decimal(str(volume_gallons)) / Decimal("10000")

    fc_deficit = max(Decimal("0"), target_fc - Decimal(str(free_chlorine_ppm)))
    chlorine_grams = fc_deficit * dose_const * vol_factor

    ta_deficit = max(Decimal("0"), Decimal(str(TA_TARGET)) - Decimal(str(total_alkalinity_ppm)))
    alk_grams = ta_deficit * Decimal(str(ALK_DOSE_PER_PPM_PER_10K)) * vol_factor

    if Decimal(str(ph)) > Decimal("7.8"):
        chlorine_grams = chlorine_grams * Decimal(str(PH_PENALTY))

    total = chlorine_grams + alk_grams
    return _round_half_up_1dp(total)


def green_surcharge(volume_gallons):
    """Volume-tiered green-pool chemical surcharge (PRD §3.5)."""
    if volume_gallons <= 15000:
        return GREEN_TIER1_CENTS
    elif volume_gallons <= 30000:
        return GREEN_TIER2_CENTS
    else:
        return GREEN_TIER3_CENTS


def final_visit_bill(plan, was_recovery, green_pool_initial, volume_gallons, visits_remaining_before):
    """Per-visit billed_amount_cents (integer cents, no rounding).

    Args:
      plan: the funding ServicePlan record.
      was_recovery: True iff the completing visit was RECOVERY_SCHEDULED.
      green_pool_initial: True iff this was a SCHEDULED visit completed with green_pool=true.
      volume_gallons: the pool's volume (for the green tier).
      visits_remaining_before: plan.visits_remaining immediately BEFORE this completion.
    """
    base = plan["per_visit_rate_cents"]
    recovery_add = RECOVERY_SURCHARGE_CENTS if was_recovery else 0
    green_add = green_surcharge(volume_gallons) if green_pool_initial else 0
    gross = base + recovery_add + green_add

    # Prepaid coverage: RECURRING plan with prepaid visits remaining covers the
    # base portion; surcharges are ALWAYS billed (PRD §3.5).
    if plan["plan_type"] == "RECURRING" and visits_remaining_before > 0:
        return recovery_add + green_add
    return gross


def repair_total(labor_minutes, severity, quoted_parts_cents):
    """WorkOrder repair_total_cents (PRD §3.9), pinned order of operations.

    labor billed in whole ceil hours -> severity multiplier on labor only ->
    add parts -> single tax round at the very end, round-half-up.
    """
    hours = math.ceil(labor_minutes / 60.0)
    labor_cost = Decimal(hours) * Decimal(LABOR_RATE_PER_HOUR_CENTS)
    sev_mult = Decimal(SEVERITY_MULT[severity])
    labor_adj = labor_cost * sev_mult
    pre_tax = labor_adj + Decimal(quoted_parts_cents)
    taxed = pre_tax * (Decimal("1") + Decimal(TAX_RATE))
    return _round_half_up_int(taxed)


def invoice_total(visit_part, repair_part):
    """Invoice amount_cents = sum of referenced parts (integer cents, no rounding)."""
    return visit_part + repair_part
