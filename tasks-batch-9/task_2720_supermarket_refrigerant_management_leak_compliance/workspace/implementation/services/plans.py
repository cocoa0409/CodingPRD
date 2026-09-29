"""Retrofit compatibility scoring (PRD 3.7)."""
from decimal import Decimal

import constants
import util

ZERO = Decimal("0")
HUNDRED = Decimal("100.0")


def gwp_reduction_pct(current_type, target_type):
    """Percent GWP reduction, floored at 0.0 and rounded to one decimal."""
    current_gwp = Decimal(int(current_type["gwp"]))
    target_gwp = Decimal(int(target_type["gwp"]))
    if current_gwp <= ZERO:
        return util.q1(ZERO)
    reduction = util.q1((current_gwp - target_gwp) / current_gwp * Decimal(100))
    if reduction < ZERO:
        return util.q1(ZERO)
    return reduction


def family_component(current_type, target_type):
    current_family = current_type["ods_class"]
    target_family = target_type["ods_class"]
    if current_family == target_family:
        return Decimal("100.0")
    pair = {current_family, target_family}
    if pair == {"HFC", "HFO"}:
        return Decimal("70.0")
    return Decimal("50.0")


def compatibility(current_type, target_type):
    """Return (score, result). Components are NOT pre-rounded (PRD 3.7)."""
    current_gwp = Decimal(int(current_type["gwp"]))
    target_gwp = Decimal(int(target_type["gwp"]))
    delta = current_gwp - target_gwp
    if delta < ZERO:
        delta = ZERO
    denominator = current_gwp if current_gwp > Decimal(1) else Decimal(1)
    gwp_component = HUNDRED * delta / denominator
    if current_type["pressure_class"] == target_type["pressure_class"]:
        pressure_component = Decimal("100.0")
    else:
        pressure_component = Decimal("40.0")
    family = family_component(current_type, target_type)
    score = util.q1(Decimal("0.45") * gwp_component
                    + Decimal("0.30") * pressure_component
                    + Decimal("0.25") * family)
    return score, classify(score)


def classify(score):
    if score >= constants.COMPATIBLE_FLOOR:
        return "COMPATIBLE"
    if score >= constants.CONDITIONALLY_COMPATIBLE_FLOOR:
        return "CONDITIONALLY_COMPATIBLE"
    return "INCOMPATIBLE"


def score_plan(plan, system, refrigerant_types):
    """Recompute a plan's compatibility fields in place.

    A RETIRE plan bypasses chemistry scoring entirely (PRD 3.7).
    """
    if plan["plan_type"] == "RETIRE":
        plan["compatibility_score"] = Decimal("100.0")
        plan["compatibility_result"] = "COMPATIBLE"
        plan["gwp_reduction_pct"] = util.q1(ZERO)
        return
    current_type = refrigerant_types.get(system["refrigerant_type_id"])
    target_type = refrigerant_types.get(plan["target_refrigerant_type_id"])
    if current_type is None or target_type is None:
        return
    score, result = compatibility(current_type, target_type)
    plan["compatibility_score"] = score
    plan["compatibility_result"] = result
    plan["gwp_reduction_pct"] = gwp_reduction_pct(current_type, target_type)
