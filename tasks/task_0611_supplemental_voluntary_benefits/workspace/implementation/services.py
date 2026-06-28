"""Shared business-logic services: lookups, cross-aggregate checks, derived-field
reconciliation, and cascade side effects (PRD §2.7, §2.8, §3).

These are invoked from the route handlers. Each mutation that touches a resource
bumps that resource's version/updated_at via db.touch (PRD §2.4, §2.8).
"""

import calculations
import errors
from db import db


# --------------------------------------------------------------------------- #
# Lookups (existence, validated left-to-right by the caller)                  #
# --------------------------------------------------------------------------- #

def find_employer(eid):
    return db.employers.get(eid)


def find_plan_product(pid):
    return db.plan_products.get(pid)


def find_period(pid):
    return db.enrollment_periods.get(pid)


def find_employee(eid):
    return db.employees.get(eid)


def find_account(aid):
    return db.disbursement_accounts.get(aid)


def find_enrollment(eid):
    return db.enrollments.get(eid)


def find_claim(cid):
    return db.claims.get(cid)


def schedule_items_for_product(plan_product_id):
    return [
        s for s in db.schedule_items.all()
        if s["plan_product_id"] == plan_product_id
    ]


def schedule_item_for_event(plan_product_id, event_code):
    for s in db.schedule_items.all():
        if s["plan_product_id"] == plan_product_id and s["event_code"] == event_code:
            return s
    return None


def locked_election_for_enrollment(enrollment_id):
    for e in db.section125_elections.all():
        if e["enrollment_id"] == enrollment_id and e["status"] == "LOCKED":
            return e
    return None


def settled_disbursement_for_claim(claim_id):
    for d in db.disbursements.all():
        if d["claim_id"] == claim_id and d["status"] == "SETTLED":
            return d
    return None


# --------------------------------------------------------------------------- #
# Derived-field reconciliation (PRD §3.4, §2.8)                               #
# --------------------------------------------------------------------------- #

def recompute_employee_total_deduction(employee):
    """Employee.total_weekly_deduction_cents = sum of weekly_deduction_cents over
    this employee's ACTIVE enrollments (PRD §3.4). This recomputation is itself a
    mutation -> bump version/updated_at (PRD §2.4)."""
    total = 0
    for enr in db.enrollments.all():
        if enr["employee_id"] == employee["id"] and enr["lifecycle_status"] == "ACTIVE":
            total += enr["weekly_deduction_cents"]
    employee["total_weekly_deduction_cents"] = total
    db.employees.touch(employee)


def recompute_benefit_remaining(enrollment):
    """benefit_remaining_cents = product cap - benefit_paid_cents, floored at 0."""
    product = find_plan_product(enrollment["plan_product_id"])
    cap = product["annual_benefit_cap_cents"]
    enrollment["benefit_remaining_cents"] = calculations.benefit_remaining(
        cap, enrollment["benefit_paid_cents"]
    )


def debit_benefit_ledger(enrollment, amount_cents):
    """Increase benefit_paid_cents (non-wellness approval). Mutates the enrollment."""
    enrollment["benefit_paid_cents"] += amount_cents
    recompute_benefit_remaining(enrollment)
    db.enrollments.touch(enrollment)


def credit_benefit_ledger(enrollment, amount_cents):
    """Credit benefit_paid_cents back by amount (compensating reversal). Mutates."""
    enrollment["benefit_paid_cents"] -= amount_cents
    if enrollment["benefit_paid_cents"] < 0:
        enrollment["benefit_paid_cents"] = 0
    recompute_benefit_remaining(enrollment)
    db.enrollments.touch(enrollment)


# --------------------------------------------------------------------------- #
# Cascade: terminate one enrollment (ACTIVE -> TERMINATED) (PRD §3.6)         #
# --------------------------------------------------------------------------- #

def terminate_enrollment_core(enrollment):
    """Apply the ACTIVE -> TERMINATED transition with all side effects (PRD §3.6).

    Side effects:
      - lifecycle_status = TERMINATED
      - funding_status = LAPSED
      - revoke a LOCKED Section125Election (qualifying_event = TERMINATION)
      - recompute the owning employee's total_weekly_deduction_cents
    Assumes the precondition (lifecycle_status == ACTIVE) is already checked.
    """
    enrollment["lifecycle_status"] = "TERMINATED"
    enrollment["funding_status"] = "LAPSED"
    db.enrollments.touch(enrollment)

    election = locked_election_for_enrollment(enrollment["id"])
    if election is not None:
        election["status"] = "REVOKED"
        election["qualifying_event"] = "TERMINATION"
        db.section125_elections.touch(election)

    employee = find_employee(enrollment["employee_id"])
    if employee is not None:
        recompute_employee_total_deduction(employee)
