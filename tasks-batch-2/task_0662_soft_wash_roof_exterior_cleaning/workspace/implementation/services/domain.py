"""Derived-field recompute + cascade side effects (PRD §2.9, §3.5–§3.10)."""
from db import db, touch


def recompute_outstanding_balance(customer):
    """Sum amount_due_cents over the customer's ISSUED/DISPUTED invoices.

    Floored at 0. Recompute is itself a mutation: bump updated_at/version.
    """
    total = 0
    for inv in db.invoices.values():
        if inv["customer_id"] == customer["id"] and inv["status"] in ("ISSUED", "DISPUTED"):
            total += inv["amount_due_cents"]
    if total < 0:
        total = 0
    customer["outstanding_balance_cents"] = total
    touch(customer)


def release_assignment(assignment):
    """Release a RESERVED/CONFIRMED assignment as a cascade side effect.

    Frees the interval and decrements the technician's scheduled_minutes by
    this assignment's duration_minutes. Each touched resource is mutated.
    """
    assignment["status"] = "RELEASED"
    touch(assignment)
    tech = db.technicians.get(assignment["technician_id"])
    if tech is not None:
        tech["scheduled_minutes"] = tech["scheduled_minutes"] - assignment["duration_minutes"]
        if tech["scheduled_minutes"] < 0:
            tech["scheduled_minutes"] = 0
        touch(tech)


def release_visit_assignments(visit):
    """Release all RESERVED/CONFIRMED assignments for a visit."""
    for a in db.crew_assignments.values():
        if a["visit_id"] == visit["id"] and a["status"] in ("RESERVED", "CONFIRMED"):
            release_assignment(a)


def backing_quote_for_visit(visit):
    """Return the ServiceQuote that prices a visit.

    Visit.quote_id when set, else RecurringPlan(plan_id).source_quote_id.
    """
    if visit.get("quote_id"):
        return db.quotes.get(visit["quote_id"])
    if visit.get("plan_id"):
        plan = db.recurring_plans.get(visit["plan_id"])
        if plan is not None:
            return db.quotes.get(plan["source_quote_id"])
    return None
