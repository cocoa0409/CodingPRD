"""Incentive payment endpoints."""

from __future__ import annotations

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object
from routes.common import paginate, fetch_or_404

bp = Blueprint("payments", __name__)


@bp.get("/efficiency/incentive_payments")
def list_payments():
    require_roles({"ProgramManager", "Contractor", "Customer"})
    items = list(db.payments.values())
    project_id = request.args.get("project_id")
    payee_role = request.args.get("payee_role")
    payee_id = request.args.get("payee_id")
    status = request.args.get("status")
    if project_id is not None:
        items = [p for p in items if p.get("project_id") == project_id]
    if payee_role is not None:
        items = [p for p in items if p.get("payee_role") == payee_role]
    if payee_id is not None:
        items = [p for p in items if p.get("payee_id") == payee_id]
    if status is not None:
        items = [p for p in items if p.get("status") == status]
    return paginate(items)


@bp.get("/efficiency/incentive_payments/<payment_id>")
def get_payment(payment_id):
    require_roles({"ProgramManager", "Contractor", "Customer"})
    return success_object(fetch_or_404(db.payments, payment_id, "IncentivePayment"))


@bp.post("/efficiency/incentive_payments/<payment_id>/disburse")
def disburse_payment(payment_id):
    require_roles({"ProgramManager"})
    payment = fetch_or_404(db.payments, payment_id, "IncentivePayment")
    if payment["status"] != "AUTHORIZED":
        raise errors.invalid_state(f"Payment in {payment['status']} cannot be disbursed")
    payment["status"] = "PAID"
    db.touch(payment)
    project = db.projects.get(payment["project_id"])
    if project is not None:
        program = db.programs.get(project["program_id"])
        if program is not None:
            # Pay the provisional up front
            program["paid_cents"] = int(program.get("paid_cents") or 0) + int(payment.get("amount_provisional_cents") or 0)
            db.touch(program)
    return success_object(payment)


@bp.post("/efficiency/incentive_payments/<payment_id>/reconcile")
def reconcile_payment(payment_id):
    require_roles({"ProgramManager"})
    payment = fetch_or_404(db.payments, payment_id, "IncentivePayment")
    if payment["status"] != "PAID":
        raise errors.invalid_state(f"Payment in {payment['status']} cannot be reconciled")
    delta = int(payment.get("reconciliation_delta_cents") or 0)
    if delta == 0:
        raise errors.nothing_to_reconcile()
    payment["status"] = "RECONCILED"
    db.touch(payment)
    project = db.projects.get(payment["project_id"])
    if project is not None:
        program = db.programs.get(project["program_id"])
        if program is not None:
            program["paid_cents"] = int(program.get("paid_cents") or 0) + delta
            db.touch(program)
    return success_object(payment)


@bp.post("/efficiency/incentive_payments/<payment_id>/void")
def void_payment(payment_id):
    require_roles({"ProgramManager"})
    payment = fetch_or_404(db.payments, payment_id, "IncentivePayment")
    if payment["status"] not in ("DRAFT", "AUTHORIZED"):
        raise errors.invalid_state(f"Payment in {payment['status']} cannot be voided")
    payment["status"] = "VOID"
    db.touch(payment)
    return success_object(payment)
