"""RepairTicket endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import errors
import validation as v
from db import store, new_entity, touch, clock, format_instant
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.catalog import recompute_model_counts

bp = Blueprint("repairs", __name__)

ACTIONS = {"DIAGNOSE", "START_REPAIR", "SUBMIT_QA", "QA_PASS", "QA_FAIL"}


@bp.post("/api/repair-tickets")
def create_repair_ticket():
    actor = require_roles(["RepairTechnician"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {"device_unit_id", "issue_description"})
    device_unit_id = v.req_string(body, "device_unit_id")
    issue_description = v.req_string(body, "issue_description")

    unit = store.device_units.get(device_unit_id)
    if unit is None:
        raise errors.not_found("DeviceUnit not found")
    if unit["status"] not in ("DEPLOYED", "IN_STOCK"):
        raise errors.invalid_state("Unit must be DEPLOYED or IN_STOCK at intake")

    ticket = new_entity()
    ticket.update({
        "device_unit_id": device_unit_id,
        "issue_description": issue_description,
        "technician_user_id": actor.user_id,
        "loan_agreement_id": None,
        "rework_count": 0,
        "status": "INTAKE",
    })
    store.repair_tickets[ticket["id"]] = ticket
    return success_object(ticket, status=201)


@bp.get("/api/repair-tickets/<tid>")
def get_repair_ticket(tid):
    require_roles(ALL_ROLES)
    ticket = store.repair_tickets.get(tid)
    if ticket is None:
        raise errors.not_found("RepairTicket not found")
    return success_object(ticket)


@bp.post("/api/repair-tickets/<tid>/advance")
def advance_repair_ticket(tid):
    require_roles(["RepairTechnician"])
    body = v.require_body(request.get_json(silent=True))
    v.reject_unknown_fields(body, {"action", "needs_loaner"})
    action = v.req_enum(body, "action", ACTIONS)
    needs_loaner = v.opt_bool(body, "needs_loaner", default=False)

    ticket = store.repair_tickets.get(tid)
    if ticket is None:
        raise errors.not_found("RepairTicket not found")

    unit = store.device_units.get(ticket["device_unit_id"])
    if unit is None:
        raise errors.not_found("DeviceUnit not found")

    status = ticket["status"]

    if action == "DIAGNOSE":
        if status != "INTAKE":
            raise errors.invalid_state("DIAGNOSE requires INTAKE")
        ticket["status"] = "DIAGNOSED"
        touch(ticket)
        return success_object(ticket)

    if action == "START_REPAIR":
        if status != "DIAGNOSED":
            raise errors.invalid_state("START_REPAIR requires DIAGNOSED")
        now = clock.now()

        # Atomicity: pre-check the loaner pool before committing any mutation.
        loaner_unit = None
        if needs_loaner:
            pool = [
                u for u in store.device_units.values()
                if u["status"] == "IN_STOCK"
                and u["condition"] == "LOANER"
                and u["device_model_id"] == unit["device_model_id"]
            ]
            if not pool:
                raise errors.no_eligible_unit()
            pool.sort(key=lambda u: (u["created_at"], u["id"]))
            loaner_unit = pool[0]

        # Move the ticket's own unit to IN_REPAIR
        unit["status"] = "IN_REPAIR"
        touch(unit)
        recompute_model_counts(unit["device_model_id"])

        if needs_loaner and loaner_unit is not None:
            # Link 1: create LoanAgreement
            loan = new_entity()
            loan.update({
                "client_id": None,
                "device_unit_id": loaner_unit["id"],
                "device_order_id": None,
                "repair_ticket_id": ticket["id"],
                "loaned_at": clock.now_iso(),
                "due_at": format_instant(now + timedelta(days=30)),
                "returned_at": None,
                "overdue_days": 0,
                "status": "ACTIVE",
            })
            store.loan_agreements[loan["id"]] = loan
            ticket["loan_agreement_id"] = loan["id"]
            # Link 2/3: move loaner unit IN_STOCK -> ON_LOAN, recompute counts
            loaner_unit["status"] = "ON_LOAN"
            touch(loaner_unit)
            recompute_model_counts(loaner_unit["device_model_id"])

        ticket["status"] = "IN_REPAIR"
        touch(ticket)
        return success_object(ticket)

    if action == "SUBMIT_QA":
        if status != "IN_REPAIR":
            raise errors.invalid_state("SUBMIT_QA requires IN_REPAIR")
        ticket["status"] = "QA_CHECK"
        touch(ticket)
        return success_object(ticket)

    if action == "QA_FAIL":
        if status != "QA_CHECK":
            raise errors.invalid_state("QA_FAIL requires QA_CHECK")
        ticket["status"] = "IN_REPAIR"
        ticket["rework_count"] += 1
        touch(ticket)
        return success_object(ticket)

    if action == "QA_PASS":
        if status != "QA_CHECK":
            raise errors.invalid_state("QA_PASS requires QA_CHECK")
        loan_id = ticket.get("loan_agreement_id")
        if loan_id is not None:
            loan = store.loan_agreements.get(loan_id)
            if loan is not None and loan["status"] in ("ACTIVE", "OVERDUE"):
                raise errors.loan_still_active()
        ticket["status"] = "RESOLVED"
        touch(ticket)
        unit["status"] = "IN_STOCK"
        touch(unit)
        recompute_model_counts(unit["device_model_id"])
        return success_object(ticket)

    # unreachable (enum-validated)
    raise errors.validation("Unknown action")
