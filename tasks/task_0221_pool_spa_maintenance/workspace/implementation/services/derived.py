"""Derived-field reconciliation (PRD §2.4, §3.1, §3.3).

Recomputing a pool's open_work_order_count or balance_due_cents, or a plan's
visits_remaining, is a mutation of the owning resource: it refreshes updated_at
and increments version just like any client-set field.
"""
from db import db
from services.common import touch

# WorkOrder statuses that count as "outstanding" for open_work_order_count.
_OPEN_WO_STATUSES = {"OPEN", "DIAGNOSED", "ON_HOLD", "AWAITING_APPROVAL"}


def recompute_open_work_order_count(pool):
    """Set pool.open_work_order_count and bump the pool (a mutation)."""
    count = sum(
        1
        for wo in db.work_orders.values()
        if wo["pool_id"] == pool["id"] and wo["status"] in _OPEN_WO_STATUSES
    )
    pool["open_work_order_count"] = count
    touch(pool)


def recompute_balance_due_cents(pool):
    """Set pool.balance_due_cents (sum of ISSUED invoice amounts) and bump it."""
    total = sum(
        inv["amount_cents"]
        for inv in db.invoices.values()
        if inv["pool_id"] == pool["id"] and inv["status"] == "ISSUED"
    )
    pool["balance_due_cents"] = total
    touch(pool)


def compute_visits_remaining(plan):
    """Pure compute of a plan's visits_remaining (no mutation/version bump).

    ONE_TIME: 1 minus count of this plan's visits that are COMPLETED or SKIPPED
              (0 or 1).
    RECURRING: prepaid_visit_count minus count of this plan's COMPLETED visits,
               floored at 0.
    """
    if plan["plan_type"] == "ONE_TIME":
        consumed = sum(
            1
            for v in db.visits.values()
            if v["plan_id"] == plan["id"] and v["status"] in ("COMPLETED", "SKIPPED")
        )
        return max(0, 1 - consumed)
    completed = sum(
        1
        for v in db.visits.values()
        if v["plan_id"] == plan["id"] and v["status"] == "COMPLETED"
    )
    return max(0, plan["prepaid_visit_count"] - completed)


def recompute_visits_remaining(plan):
    """Set plan.visits_remaining and bump the plan (a mutation)."""
    plan["visits_remaining"] = compute_visits_remaining(plan)
    touch(plan)
