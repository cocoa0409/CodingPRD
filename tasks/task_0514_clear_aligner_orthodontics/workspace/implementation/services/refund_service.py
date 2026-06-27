"""Refund settlement cascade (PRD §3.11)."""
from db import db
from models import touch
from services.case_service import void_step
from services.store import (steps_for_case, financing_for_case,
                            installments_for_plan, shipments_for_step)


def settle_cascade(case):
    """Drive the case to REFUNDED and unwind atomically (PRD §3.11).

    - case.refund_issued_cents already set by caller, case -> REFUNDED
    - cancel every non-DELIVERED shipment for the case's steps
    - void every PLANNED/IN_PRODUCTION step (decrement planned_step_count)
    - if a financing plan exists: billing_state CANCELLED, waive SCHEDULED/LATE
      installments
    """
    case["status"] = "REFUNDED"
    touch(case)

    steps = steps_for_case(case["id"])
    # cancel non-DELIVERED shipments for the case's steps
    for step in steps:
        for ship in shipments_for_step(step["id"]):
            if ship["status"] != "DELIVERED" and ship["status"] != "CANCELLED":
                ship["status"] = "CANCELLED"
                touch(ship)
    # void unstarted steps
    for step in steps:
        void_step(step, case)

    # cancel financing + waive installments (PRD §3.11: "if a financing plan
    # exists ... its billing_state is set to CANCELLED and all of its SCHEDULED
    # (and LATE) installments are marked WAIVED"). Already-terminal plans
    # (PAID_OFF / CANCELLED) are left untouched.
    for plan in financing_for_case(case["id"]):
        if plan["billing_state"] in ("PENDING_ACTIVATION", "ACTIVE"):
            plan["billing_state"] = "CANCELLED"
            touch(plan)
            for inst in installments_for_plan(plan["id"]):
                if inst["status"] in ("SCHEDULED", "LATE"):
                    inst["status"] = "WAIVED"
                    touch(inst)
