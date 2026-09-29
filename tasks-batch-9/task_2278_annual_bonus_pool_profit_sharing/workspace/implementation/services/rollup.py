"""Roll-up chain: award -> pool -> plan (PRD 2.7) and the conserved-quantity
recomputations (PRD 2.11).

Every recompute that actually changes a stored field bumps that record's own
`version` and `updated_at`, including cascaded children.
"""

from decimal import Decimal

import db
from services import calc

POOL_DERIVED = (
    "eligible_target_cents", "eligible_headcount", "max_top_tier_count",
    "allocated_cents", "available_cents", "utilization_pct",
    "top_tier_award_count", "distribution_status",
)

PLAN_GOVERNANCE = (
    "over_allocated_pool_count", "under_utilized_pool_count", "governance_posture",
)


def _snapshot(rec, fields):
    return tuple(rec.get(name) for name in fields)


# ---------------------------------------------------------------------------
# Award derived money fields
# ---------------------------------------------------------------------------
def refresh_award_money(award):
    award["allocation_ratio"] = calc.allocation_ratio(
        award["proposed_allocation_cents"], award["prorated_target_cents"])
    award["final_award_cents"] = (award["proposed_allocation_cents"]
                                 + award["adjustment_total_cents"])


# ---------------------------------------------------------------------------
# Pool distribution state
# ---------------------------------------------------------------------------
def recompute_pool(pool, bump=True):
    before = _snapshot(pool, POOL_DERIVED)
    awards = db.pool_awards(pool["id"])

    eligible = [a for a in awards
                if a["eligibility_status"] != "INELIGIBLE_MIN_SERVICE"]
    pool["eligible_target_cents"] = sum(a["prorated_target_cents"] for a in eligible)
    pool["eligible_headcount"] = len(eligible)
    pool["max_top_tier_count"] = calc.max_top_tier_count(pool["eligible_headcount"])

    allocated = sum(a["proposed_allocation_cents"] + a["adjustment_total_cents"]
                    for a in awards
                    if a["allocation_status"] in calc.ALLOCATED_STATUSES)
    pool["allocated_cents"] = allocated
    pool["available_cents"] = pool["funded_cents"] - allocated
    pool["utilization_pct"] = calc.utilization_pct(allocated, pool["funded_cents"])
    pool["top_tier_award_count"] = sum(
        1 for a in awards
        if a["allocation_status"] in calc.ALLOCATED_STATUSES
        and Decimal(str(a["allocation_ratio"])) >= calc.TOP_TIER_RATIO)
    pool["distribution_status"] = calc.distribution_status(
        pool["eligible_headcount"], allocated, pool["funded_cents"],
        pool["min_utilization_cents"])

    changed = _snapshot(pool, POOL_DERIVED) != before
    if changed and bump:
        db.touch(pool)
    return changed


def recompute_pools(plan, bump=True):
    for pool in db.plan_pools(plan["id"]):
        recompute_pool(pool, bump=bump)


# ---------------------------------------------------------------------------
# Plan governance bubble-up
# ---------------------------------------------------------------------------
def apply_plan_governance(plan):
    """Mutate the plan's governance roll-up. Returns True when it changed."""
    before = _snapshot(plan, PLAN_GOVERNANCE)
    pools = db.plan_pools(plan["id"])
    over = sum(1 for p in pools if p["distribution_status"] == "OVER_ALLOCATED")
    under = sum(1 for p in pools if p["distribution_status"] == "UNDER_UTILIZED")
    plan["over_allocated_pool_count"] = over
    plan["under_utilized_pool_count"] = under
    plan["governance_posture"] = calc.governance_posture(over, under)
    return _snapshot(plan, PLAN_GOVERNANCE) != before


def recompute_plan_governance(plan, bump=True):
    changed = apply_plan_governance(plan)
    if changed and bump:
        db.touch(plan)
    return changed


# ---------------------------------------------------------------------------
# Conserved quantities (PRD 2.11)
# ---------------------------------------------------------------------------
def refresh_discretionary_used(plan):
    plan["discretionary_used_cents"] = sum(
        abs(a["adjustment_cents"]) for a in db.plan_adjustments(plan["id"])
        if a["status"] == "APPROVED")


def refresh_accrual_ledger(plan):
    posted = [p for p in db.plan_periods(plan["id"]) if p["status"] == "POSTED"]
    plan["accrued_base_cents"] = sum(p["period_accrual_cents"] for p in posted)
    plan["accrued_total_cents"] = sum(p["total_period_cents"] for p in posted)


def refresh_award_adjustment_total(award):
    award["adjustment_total_cents"] = sum(
        a["adjustment_cents"] for a in db.award_adjustments(award["id"])
        if a["status"] == "APPROVED")
    refresh_award_money(award)


def refresh_payout_totals(plan):
    awards = db.plan_awards(plan["id"])
    plan["paid_total_cents"] = sum(a["payout_amount_cents"] for a in awards
                                   if a["payment_status"] == "PAID")
    plan["forfeited_total_cents"] = sum(a["final_award_cents"] for a in awards
                                        if a["payment_status"] == "FORFEITED")
