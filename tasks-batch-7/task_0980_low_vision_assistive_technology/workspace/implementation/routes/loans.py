"""LoanAgreement endpoints."""

from flask import Blueprint, request

import errors
import validation as v
from db import store, touch, clock, parse_datetime
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from routes.catalog import recompute_model_counts

bp = Blueprint("loans", __name__)


@bp.get("/api/loan-agreements/<lid>")
def get_loan(lid):
    require_roles(ALL_ROLES)
    loan = store.loan_agreements.get(lid)
    if loan is None:
        raise errors.not_found("LoanAgreement not found")
    return success_object(loan)


@bp.get("/api/loan-agreements")
def list_loans():
    require_roles(ALL_ROLES)
    limit, offset = v.parse_pagination(request.args)
    items = v.apply_filters(list(store.loan_agreements.values()), [
        (request.args.get("client_id"), "client_id"),
        (request.args.get("device_unit_id"), "device_unit_id"),
        (request.args.get("device_order_id"), "device_order_id"),
        (request.args.get("repair_ticket_id"), "repair_ticket_id"),
        (request.args.get("status"), "status"),
    ])
    items = v.sort_by_created(items)
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.get("/api/loan-agreements/<lid>/repair-tickets")
def list_loan_repair_tickets(lid):
    require_roles(ALL_ROLES)
    loan = store.loan_agreements.get(lid)
    if loan is None:
        raise errors.not_found("LoanAgreement not found")
    limit, offset = v.parse_pagination(request.args)
    items = v.sort_by_created([
        t for t in store.repair_tickets.values() if t.get("loan_agreement_id") == lid
    ])
    total = len(items)
    return success_list(items[offset:offset + limit], limit, offset, total)


@bp.post("/api/loan-agreements/<lid>/return")
def return_loan(lid):
    require_roles(["RepairTechnician", "VisionSpecialist"])
    loan = store.loan_agreements.get(lid)
    if loan is None:
        raise errors.not_found("LoanAgreement not found")
    if loan["status"] not in ("ACTIVE", "OVERDUE"):
        raise errors.invalid_state("Loan cannot be returned from its current state")

    now = clock.now()
    loan["status"] = "RETURNED"
    loan["returned_at"] = clock.now_iso()
    due_at = parse_datetime(loan["due_at"])
    days = int((now - due_at).total_seconds() // 86400)
    loan["overdue_days"] = days if days > 0 else 0
    touch(loan)

    unit = store.device_units.get(loan["device_unit_id"])
    if unit is not None and unit["status"] == "ON_LOAN":
        unit["status"] = "IN_STOCK"
        touch(unit)
        recompute_model_counts(unit["device_model_id"])

    return success_object(loan)
