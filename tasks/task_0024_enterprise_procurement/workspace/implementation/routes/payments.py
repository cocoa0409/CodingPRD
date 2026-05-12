"""Payment + PaymentSchedule endpoints (PRD §3.7 / §3.10)."""

from __future__ import annotations

from flask import Blueprint, g, jsonify

from db import db, stamp_create, stamp_update, serialize, serialize_list, order_by_created_then_seq
from errors import err
from middleware import enforce_role, require_roles
from response import success_object
from services.approval import steps_for_po
from services.lookups import find_payment, find_payment_schedule, find_purchase_order, find_invoice
from validate import get_json_body, require_fields, require_string

bp = Blueprint("payments", __name__)


@bp.get("/purchase-orders/<rid>/payment-schedule")
@require_roles("Buyer", "FinanceApprover", "GeneralManager", "Supplier")
def get_payment_schedule(rid: str):
    po = find_purchase_order(rid)
    enforce_role()
    if g.user_role == "Supplier" and g.user_id != po.get("supplier_id"):
        raise err("ERR_FORBIDDEN", "Supplier may only view their own POs.")
    rows = [s for s in db.payment_schedules.values() if s.get("purchase_order_id") == po["id"]]
    rows = sorted(rows, key=lambda s: int(s.get("installment_no", 0)))
    return jsonify(success_object(serialize_list(rows))), 200


@bp.post("/payments")
@require_roles("FinanceApprover")
def apply_payment():
    body = get_json_body()
    require_fields(body, ["payment_schedule_id", "invoice_id"])
    sched_id = require_string(body["payment_schedule_id"], "payment_schedule_id")
    inv_id = require_string(body["invoice_id"], "invoice_id")

    sched = db.payment_schedules.get(sched_id)
    if sched is None:
        raise err("ERR_VALIDATION", "payment_schedule_id does not exist.")
    inv = db.invoices.get(inv_id)
    if inv is None:
        raise err("ERR_VALIDATION", "invoice_id does not exist.")

    if inv["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Invoice is not APPROVED.")
    # Race-loser: if schedule entry is no longer PENDING, fail with the
    # specific application-race error.
    if sched["status"] != "PENDING":
        raise err("ERR_PAYMENT_ALREADY_APPLIED",
                  "PaymentSchedule entry is no longer PENDING.")

    # Apply
    payment = {
        "payment_schedule_id": sched_id,
        "invoice_id": inv_id,
        "amount_cents": int(sched["amount_cents"]),
        "status": "APPLIED",
        "bank_reference": None,
    }
    stamp_create(payment, common=True)
    db.payments[payment["id"]] = payment
    sched["status"] = "APPLIED"
    return jsonify(success_object(serialize(payment))), 201


@bp.post("/payments/<rid>/approve")
@require_roles("FinanceApprover")
def approve_payment(rid: str):
    p = find_payment(rid)
    enforce_role()
    if p["status"] != "APPLIED":
        raise err("ERR_INVALID_STATE", "Payment is not APPLIED.")
    inv = db.invoices.get(p["invoice_id"])
    if inv is None or inv["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Bound Invoice is not APPROVED.")
    sched = db.payment_schedules.get(p["payment_schedule_id"])
    if sched is None or sched["status"] != "APPLIED":
        raise err("ERR_INVALID_STATE", "Bound PaymentSchedule is not APPLIED.")

    # Priority 8 — segregation of duties: same user must not have decided any
    # ApprovalStep on the parent PO.
    po = db.purchase_orders.get(inv.get("purchase_order_id"))
    if po is None:
        raise err("ERR_NOT_FOUND", "PurchaseOrder not found.")
    for s in steps_for_po(po["id"]):
        if s.get("decided_at") is not None and s.get("_decided_by") == g.user_id:
            raise err("ERR_SEGREGATION_OF_DUTIES",
                      "Approver previously decided an ApprovalStep on this PO.")

    p["status"] = "APPROVED"
    p["_approved_by"] = g.user_id
    stamp_update(p)
    return jsonify(success_object(serialize(p))), 200


@bp.post("/payments/<rid>/execute")
@require_roles("PlatformAdmin")
def execute_payment(rid: str):
    p = find_payment(rid)
    enforce_role()
    if p["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Payment is not APPROVED.")
    inv = db.invoices.get(p["invoice_id"])
    if inv is None or inv["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Bound Invoice is not APPROVED.")
    sched = db.payment_schedules.get(p["payment_schedule_id"])
    if sched is None or sched["status"] != "APPLIED":
        raise err("ERR_INVALID_STATE", "Bound PaymentSchedule is not APPLIED.")
    po = db.purchase_orders.get(inv.get("purchase_order_id"))
    if po is None:
        raise err("ERR_NOT_FOUND", "PurchaseOrder not found.")

    # Optional bank-side simulation: if request body supplies `bank_failure: true`,
    # drive the payment to FAILED instead of EXECUTED. Defaults to success.
    body = get_json_body()
    bank_failure = bool(body.get("bank_failure"))
    bank_reference = body.get("bank_reference")
    if bank_reference is not None and not isinstance(bank_reference, str):
        raise err("ERR_VALIDATION", "bank_reference must be a string.")

    if bank_failure:
        p["status"] = "FAILED"
        # PaymentSchedule rolls from APPLIED back to APPLIED per PRD §3.10
        # (i.e. the schedule remains APPLIED — it's already in APPLIED, so a
        # no-op; the PRD wording reads "rolls back to APPLIED" meaning it does
        # not advance to EXECUTED).
        stamp_update(p)
        return jsonify(success_object(serialize(p))), 200

    p["status"] = "EXECUTED"
    p["bank_reference"] = bank_reference or f"bank_{p['id']}"
    sched["status"] = "EXECUTED"
    # Budget: spent += amt; committed -= amt
    ba = db.budget_accounts.get(po["budget_account_id"])
    if ba is not None:
        amt = int(p["amount_cents"])
        ba["spent_amount_cents"] = int(ba.get("spent_amount_cents", 0)) + amt
        ba["committed_amount_cents"] = int(ba.get("committed_amount_cents", 0)) - amt
        stamp_update(ba)
    stamp_update(p)

    # Invoice -> PAID if every Payment for this invoice is EXECUTED
    invoice_payments = [x for x in db.payments.values() if x.get("invoice_id") == inv["id"]]
    if invoice_payments and all(x.get("status") == "EXECUTED" for x in invoice_payments):
        if inv["status"] == "APPROVED":
            inv["status"] = "PAID"
            stamp_update(inv)

    # PO -> CLOSED if every PaymentSchedule on PO is EXECUTED/CANCELLED and every
    # Invoice for PO is APPROVED/PAID.
    _maybe_close_po(po)

    return jsonify(success_object(serialize(p))), 200


@bp.post("/payments/<rid>/cancel")
@require_roles("FinanceApprover")
def cancel_payment(rid: str):
    p = find_payment(rid)
    enforce_role()
    if p["status"] != "APPLIED":
        raise err("ERR_INVALID_STATE", "Payment is not APPLIED.")
    sched = db.payment_schedules.get(p["payment_schedule_id"])
    if sched is not None and sched["status"] == "APPLIED":
        sched["status"] = "PENDING"
    p["status"] = "CANCELLED"
    stamp_update(p)
    return jsonify(success_object(serialize(p))), 200


def _maybe_close_po(po: dict) -> None:
    """If all schedules and invoices reach terminal positive states, close PO."""
    if po["status"] != "FULFILLED":
        return
    schedules = [s for s in db.payment_schedules.values() if s.get("purchase_order_id") == po["id"]]
    if not schedules:
        return
    if not all(s.get("status") in ("EXECUTED", "CANCELLED") for s in schedules):
        return
    invoices = [i for i in db.invoices.values() if i.get("purchase_order_id") == po["id"]]
    if not invoices:
        return
    if not all(i.get("status") in ("APPROVED", "PAID") for i in invoices):
        return
    # Reconcile budget
    ba = db.budget_accounts.get(po["budget_account_id"])
    if ba is not None:
        executed = sum(int(x.get("amount_cents", 0))
                       for x in db.payments.values()
                       if x.get("status") == "EXECUTED"
                       and any(s["id"] == x.get("payment_schedule_id")
                               and s.get("purchase_order_id") == po["id"]
                               for s in schedules))
        residual = int(po["total_amount_cents"]) - executed
        if residual > 0:
            ba["committed_amount_cents"] = int(ba.get("committed_amount_cents", 0)) - residual
            stamp_update(ba)
    po["status"] = "CLOSED"
    stamp_update(po)
