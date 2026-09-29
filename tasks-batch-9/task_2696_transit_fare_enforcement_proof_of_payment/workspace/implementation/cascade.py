"""Cascade discipline (PRD 2.9): zone suspension, zone revocation, dismissal unwind."""

import calc
from core import base_record, db, ordered, touch


# ---------------------------------------------------------------------------
# Ledger append
# ---------------------------------------------------------------------------

def append_payment(citation_id, source, amount_cents, plan_id=None, hours_credited=0):
    row = base_record(versioned=False)
    row.update({
        "citation_id": citation_id,
        "plan_id": plan_id,
        "amount_cents": amount_cents,
        "source": source,
        "hours_credited": hours_credited,
        "applied_at": db.now(),
    })
    db.payments[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# Deployment voiding (shared by planner cancellation and both zone cascades)
# ---------------------------------------------------------------------------

def void_deployment(deployment, void_reason):
    deployment["status"] = "VOIDED"
    deployment["void_reason"] = void_reason
    touch(deployment)
    for encounter in ordered(calc.deployment_encounters(deployment["id"])):
        if encounter["outcome"] == "PENDING":
            encounter["outcome"] = "VOIDED"
            touch(encounter)
    calc.refresh_deployment_counters(deployment)
    return deployment


def zone_suspension_cascade(zone):
    """Link 1-3 of PRD 2.9: live deployments -> VOIDED -> PENDING encounters -> counters."""
    for deployment in ordered(list(db.deployments.values())):
        if deployment["zone_id"] != zone["id"]:
            continue
        if deployment["status"] in ("PLANNED", "ACTIVE"):
            void_deployment(deployment, "ZONE_SUSPENDED")


# ---------------------------------------------------------------------------
# Dismissal unwind (shared tail of dismissal, granted appeal and revocation)
# ---------------------------------------------------------------------------

def dismissal_unwind(citation):
    """Runs after adjudication_status/dismissal_reason_code/dismissed_at are stamped."""
    rows = calc.citation_payments(citation["id"])
    paid_in = sum(r["amount_cents"] for r in rows if r["source"] in calc.CASH_IN_SOURCES)
    reversed_out = sum(r["amount_cents"] for r in rows
                       if r["source"] == "DISMISSAL_REVERSAL")
    pre_cascade_paid = paid_in - reversed_out

    citation["settlement_status"] = "WRITTEN_OFF"
    citation["outstanding_balance_cents"] = 0

    for plan in ordered(list(db.plans.values())):
        if plan["citation_id"] == citation["id"] and plan["status"] == "ACTIVE":
            plan["status"] = "CANCELLED"
            touch(plan)
    for assignment in ordered(list(db.services.values())):
        if assignment["citation_id"] == citation["id"] and assignment["status"] == "ACTIVE":
            assignment["status"] = "CANCELLED"
            touch(assignment)

    if pre_cascade_paid > 0:
        append_payment(citation["id"], "DISMISSAL_REVERSAL", pre_cascade_paid)

    calc.refresh_citation_money(citation)
    return citation


def cancel_scheduled_hearings(citation_id):
    for hearing in ordered(list(db.hearings.values())):
        if hearing["citation_id"] == citation_id and hearing["status"] == "SCHEDULED":
            hearing["status"] = "CANCELLED"
            touch(hearing)


def zone_revocation_cascade(zone):
    """PRD 3.1: deployments first, then every live citation written in the zone."""
    zone_suspension_cascade(zone)
    for citation in ordered(list(db.citations.values())):
        if citation["zone_id"] != zone["id"]:
            continue
        if citation["adjudication_status"] not in ("ISSUED", "CONTESTED"):
            continue
        citation["adjudication_status"] = "VOID"
        citation["dismissal_reason_code"] = "ZONE_NOT_DESIGNATED"
        citation["dismissed_at"] = db.now()
        cancel_scheduled_hearings(citation["id"])
        dismissal_unwind(citation)
        touch(citation)
