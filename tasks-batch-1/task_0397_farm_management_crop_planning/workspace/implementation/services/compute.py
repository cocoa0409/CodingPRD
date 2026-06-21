"""Derived-field recomputation and calculation rules.

All formulas trace to PRD §3.6 (yield), §3.7 (cost-per-acre), §2.4/§2.5
(derived-field reconciliation -> mutation: updated_at + version bump).

Calculation precision: 2 dp, round-half-up, round once at the end of a sum
(PRD §2.8, SCAFFOLD §1.3).
"""
import db
from helpers import round2

# Parcel statuses whose plans count as "active" (PRD §3.1)
ACTIVE_PLAN_STATUSES = {"APPROVED", "GROWING", "HARVESTING"}


# --------------------------------------------------------------------------
# CropPlan derived fields
# --------------------------------------------------------------------------
def recompute_planted_acres(plan):
    """Sum of acres_planted across the plan's non-voided plantings (PRD §3.5)."""
    total = sum(
        pe["acres_planted"]
        for pe in db.planting_events.values()
        if pe["crop_plan_id"] == plan["id"] and pe["status"] != "VOIDED"
    )
    plan["planted_acres"] = total


def recompute_harvested_acres(plan):
    """Sum of acres_harvested across the plan's RECORDED harvest events (PRD §3.5)."""
    total = sum(
        he["acres_harvested"]
        for he in db.harvest_events.values()
        if he["crop_plan_id"] == plan["id"] and he["status"] == "RECORDED"
    )
    plan["harvested_acres"] = total


def recompute_actual_input_cost(plan):
    """Sum of applied_cost across non-voided CONFIRMED applications (PRD §3.4, §3.7).

    A non-voided record that contributes cost is one with status CONFIRMED
    (applied_cost is only stamped/recomputed at confirm). VOIDED records drop out.
    """
    total = sum(
        ar.get("applied_cost", 0) or 0
        for ar in db.application_records.values()
        if ar["crop_plan_id"] == plan["id"] and ar["status"] == "CONFIRMED"
    )
    plan["actual_input_cost"] = round2(total)


def recompute_actual_labor_cost(plan):
    """Sum of labor_cost across the plan's labor entries (PRD §3.7)."""
    total = sum(
        le["labor_cost"]
        for le in db.labor_entries.values()
        if le["crop_plan_id"] == plan["id"]
    )
    plan["actual_labor_cost"] = round2(total)


def recompute_actual_equipment_cost(plan):
    """Sum of usage_cost across the plan's RECORDED equipment usages (PRD §3.7)."""
    total = sum(
        eu["usage_cost"]
        for eu in db.equipment_usages.values()
        if eu["crop_plan_id"] == plan["id"] and eu["status"] == "RECORDED"
    )
    plan["actual_equipment_cost"] = round2(total)


def compute_provisional_cost_per_acre(plan):
    """PROVISIONAL cost-per-acre (PRD §3.7, SCAFFOLD calc cost_per_acre).

    numerator = budget_input_cost + budget_labor_cost + budget_equipment_cost
    denominator = planned_acres
    round once at the end (2 dp). Full equipment budget; no acreage-share split.
    """
    numerator = (
        plan["budget_input_cost"]
        + plan["budget_labor_cost"]
        + plan["budget_equipment_cost"]
    )
    denominator = plan["planned_acres"]
    if denominator == 0:
        return round2(0)
    return round2(numerator / denominator)


def recompute_provisional_cost_per_acre(plan):
    plan["provisional_cost_per_acre"] = compute_provisional_cost_per_acre(plan)


def compute_final_cost_per_acre(plan):
    """FINAL cost-per-acre at close (PRD §3.7, SCAFFOLD calc cost_per_acre).

    direct   = actual_input_cost + actual_labor_cost
    overhead = actual_equipment_cost, allocated by acreage-share factor f.
      f = 1 when this is the only plan harvested on the parcel for season_year;
      otherwise f = this plan's harvested_acres / sum(harvested_acres across
      CLOSED+HARVESTING plans on the parcel for that season_year).
    numerator   = direct + overhead * f
    denominator = max(harvested_acres, MIN_DENOMINATOR_GUARD=1)
    round once at the end (2 dp).
    """
    direct = plan["actual_input_cost"] + plan["actual_labor_cost"]
    overhead = plan["actual_equipment_cost"]

    my_harvested = plan["harvested_acres"]

    # Peer plans on the same parcel for the same season_year in CLOSED/HARVESTING.
    # The closing plan itself is HARVESTING at the moment final is computed (the
    # status flip to CLOSED happens together with this computation), so include
    # both CLOSED and HARVESTING; the closing plan must be counted in the pool.
    peer_sum = 0.0
    peer_count = 0
    for p in db.crop_plans.values():
        if (
            p["parcel_id"] == plan["parcel_id"]
            and p["season_year"] == plan["season_year"]
            and (p["status"] in ("CLOSED", "HARVESTING") or p["id"] == plan["id"])
        ):
            peer_sum += p["harvested_acres"]
            peer_count += 1

    if peer_count <= 1 or peer_sum == 0:
        f = 1.0
    else:
        f = my_harvested / peer_sum

    numerator = direct + overhead * f
    denominator = max(my_harvested, 1)
    return round2(numerator / denominator)


def recompute_total_yield_units(plan):
    """SUM over GRADE_A/GRADE_B harvest lots of quantity, round once (PRD §3.6)."""
    total = sum(
        lot["quantity"]
        for lot in db.harvest_lots.values()
        if lot["crop_plan_id"] == plan["id"]
        and lot["quality_status"] in ("GRADE_A", "GRADE_B")
    )
    plan["total_yield_units"] = round2(total)


# --------------------------------------------------------------------------
# Parcel derived fields (PRD §3.1, §3.4)
# --------------------------------------------------------------------------
def recompute_active_crop_plan_count(parcel):
    """Count of plans on this parcel in APPROVED/GROWING/HARVESTING (PRD §3.1)."""
    count = sum(
        1
        for p in db.crop_plans.values()
        if p["parcel_id"] == parcel["id"] and p["status"] in ACTIVE_PLAN_STATUSES
    )
    parcel["active_crop_plan_count"] = count


def recompute_reentry_blocked_until(parcel):
    """MAX reentry_clear_at over ACTIVE compliance records on the parcel (PRD §3.4).

    Compliance records denormalize crop_plan_id; resolve the parcel via the plan.
    Returns the new value (also written onto the parcel). Null if none active.
    """
    candidates = []
    for cr in db.compliance_records.values():
        if cr["status"] != "ACTIVE":
            continue
        plan = db.crop_plans.get(cr["crop_plan_id"])
        if not plan or plan["parcel_id"] != parcel["id"]:
            continue
        if cr.get("reentry_clear_at"):
            candidates.append(cr["reentry_clear_at"])
    parcel["reentry_blocked_until"] = max(candidates) if candidates else None
    return parcel["reentry_blocked_until"]
