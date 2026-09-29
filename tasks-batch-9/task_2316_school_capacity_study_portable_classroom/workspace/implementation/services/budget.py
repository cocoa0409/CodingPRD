"""Calculation budget_partition and the capital-budget invariant (PRD 2.9)."""

from db import db


def recompute(budget):
    """encumbered is an aggregation; expended is a monotone accumulator."""
    budget["encumbered_cents"] = sum(
        r["encumbered_cost_cents"]
        for r in db.requests.values()
        if r["capital_budget_id"] == budget["id"]
        and r["status"] in ("PERMITTED", "SCHEDULED")
    )
    budget["uncommitted_cents"] = (
        budget["authorized_cents"] - budget["encumbered_cents"] - budget["expended_cents"]
    )
    return budget
