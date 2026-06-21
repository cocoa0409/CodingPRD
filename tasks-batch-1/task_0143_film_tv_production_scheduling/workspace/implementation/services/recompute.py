"""Cross-aggregate recomputation of computed fields.

These functions are called whenever a mutation changes an upstream value that a
computed field depends on. Per PRD section 2.4 a computed-field change is itself a
mutation: it refreshes updated_at and increments version on the resource whose
field changed.
"""
from db import db, now_iso


def touch(record):
    """Refresh updated_at and bump version on a versioned record."""
    record["updated_at"] = now_iso()
    record["version"] = record["version"] + 1


def assignments_for_production(production_id):
    out = []
    for a in db.assignments.values():
        day = db.shooting_days.get(a["shooting_day_id"])
        if day and day["production_id"] == production_id:
            out.append(a)
    return out


def committed_cost(production):
    """committed_cost_cents = sum(estimated_cost_cents for UNPAID|APPROVED) +
    sum(paid_cost_cents for PAID)."""
    pid = production["id"]
    total = 0
    for a in assignments_for_production(pid):
        if a["payment_status"] in ("UNPAID", "APPROVED"):
            total += a["estimated_cost_cents"]
        elif a["payment_status"] == "PAID":
            total += a["paid_cost_cents"]
    return total


def recompute_committed_cost(production):
    """Recompute committed_cost_cents. When it changes, that is a computed-field
    change which is itself a mutation (PRD 2.4) -> touch once."""
    total = committed_cost(production)
    if production["committed_cost_cents"] != total:
        production["committed_cost_cents"] = total
        touch(production)


def projected_committed_with(production, replacement_assignment, new_estimated=None,
                             new_paid=None, treat_as_payment=None):
    """Compute what committed_cost_cents WOULD be if `replacement_assignment`
    had the given projected payment_status / paid_cost. Used for the budget gate
    at approve-pay without mutating state."""
    pid = production["id"]
    total = 0
    for a in assignments_for_production(pid):
        if a["id"] == replacement_assignment["id"]:
            status = treat_as_payment if treat_as_payment else a["payment_status"]
            if status in ("UNPAID", "APPROVED"):
                total += new_estimated if new_estimated is not None else a["estimated_cost_cents"]
            elif status == "PAID":
                total += new_paid if new_paid is not None else a["paid_cost_cents"]
        else:
            if a["payment_status"] in ("UNPAID", "APPROVED"):
                total += a["estimated_cost_cents"]
            elif a["payment_status"] == "PAID":
                total += a["paid_cost_cents"]
    return total


def budget_line_for(production_id, category):
    for bl in db.budget_lines.values():
        if bl["production_id"] == production_id and bl["category"] == category:
            return bl
    return None


def recompute_variance(budget_line):
    budget_line["variance_cents"] = budget_line["estimated_cents"] - budget_line["actual_cents"]
