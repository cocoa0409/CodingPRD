"""Invoice routes: generation, lifecycle, payments."""
from datetime import timedelta

from flask import Blueprint, request

import core
from core import (
    db, require, get_body, get_or_404, base_record, touch, success,
    list_response, req_str, req_dt, opt_enum, check_owner, ApiError,
    now_clock, rhu, INVOICE_DUE_DAYS, TAX_RATE, DELIVERY_FLAT_CENTS,
)
from services import ser_invoice, storage_proration, sort_created_key

bp = Blueprint("invoices", __name__)

PRORATION_MODES = {"FULL_MONTH", "PRORATED"}
INVOICE_STATUSES = {"DRAFT", "ISSUED", "PAID", "VOID"}


@bp.post("/invoices/generate")
def generate_invoice():
    require("BillingAdmin")
    body = get_body()
    member_id = req_str(body, "member_id")
    agreement_id = req_str(body, "agreement_id")
    period_start_at = req_dt(body, "period_start_at")
    period_end_at = req_dt(body, "period_end_at")
    proration_mode = opt_enum(body, "proration_mode", PRORATION_MODES, "FULL_MONTH")
    get_or_404(db.members, member_id)
    agr = get_or_404(db.agreements, agreement_id)

    line_items = []
    # STORAGE (always one line).
    line_items.append({"kind": "STORAGE", "amount_cents": storage_proration(agr, proration_mode)})
    # MONITORING (one combined line when active subscriptions exist).
    active_subs = [s for s in db.monitorings.values()
                   if s["agreement_id"] == agreement_id and s["status"] == "ACTIVE"]
    if active_subs:
        mon_total = rhu(sum(s["monthly_fee_cents"] for s in active_subs))
        line_items.append({"kind": "MONITORING", "amount_cents": mon_total})
    # SERVICE (one per COMPLETED, uninvoiced order).
    svc = [o for o in db.service_orders.values()
           if o["agreement_id"] == agreement_id and o["status"] == "COMPLETED"
           and not o.get("_invoiced")]
    for o in sorted(svc, key=sort_created_key):
        line_items.append({"kind": "SERVICE", "amount_cents": o["final_cost_cents"]})
        o["_invoiced"] = True
    # DELIVERY (one per RETURNED, uninvoiced job for the agreement's vehicle).
    jobs = [d for d in db.delivery_jobs.values()
            if d["vehicle_id"] == agr["vehicle_id"] and d["status"] == "RETURNED"
            and not d.get("_invoiced")]
    for d in sorted(jobs, key=sort_created_key):
        line_items.append({"kind": "DELIVERY", "amount_cents": DELIVERY_FLAT_CENTS})
        d["_invoiced"] = True

    subtotal = sum(li["amount_cents"] for li in line_items)
    from decimal import Decimal
    tax = sum(rhu(Decimal(li["amount_cents"]) * Decimal(TAX_RATE)) for li in line_items)
    total = subtotal + tax

    rec = base_record()
    rec.update({
        "member_id": member_id,
        "agreement_id": agreement_id,
        "period_start_at": period_start_at,
        "period_end_at": period_end_at,
        "proration_mode": proration_mode,
        "line_items": line_items,
        "subtotal_cents": subtotal,
        "tax_cents": tax,
        "total_cents": total,
        "due_at": None,
        "status": "DRAFT",
    })
    db.invoices[rec["id"]] = rec
    return success(ser_invoice(rec), status=201)


@bp.get("/invoices/<iid>")
def get_invoice(iid):
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    rec = get_or_404(db.invoices, iid)
    return success(ser_invoice(rec))


@bp.get("/invoices")
def list_invoices():
    require("Member", "VaultManager", "ConciergeTech", "BillingAdmin")
    member_id = request.args.get("member_id")
    agreement_id = request.args.get("agreement_id")
    status = request.args.get("status")
    items = [inv for inv in db.invoices.values()
             if (member_id is None or inv["member_id"] == member_id)
             and (agreement_id is None or inv["agreement_id"] == agreement_id)
             and (status is None or inv["status"] == status)]
    return list_response(items, ser_invoice)


@bp.post("/invoices/<iid>/issue")
def issue_invoice(iid):
    require("BillingAdmin")
    inv = get_or_404(db.invoices, iid)
    if inv["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Invoice is not DRAFT")
    inv["due_at"] = now_clock() + timedelta(days=INVOICE_DUE_DAYS)
    inv["status"] = "ISSUED"
    touch(inv)
    return success(ser_invoice(inv))


@bp.post("/invoices/<iid>/pay")
def pay_invoice(iid):
    uid, role = require("Member", "BillingAdmin")
    inv = get_or_404(db.invoices, iid)
    check_owner(role, uid, inv["member_id"])
    if inv["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", 409, "Invoice is not ISSUED")
    inv["status"] = "PAID"
    db.payments.append({"member_id": inv["member_id"], "amount_cents": inv["total_cents"]})
    touch(inv)
    return success(ser_invoice(inv))


@bp.post("/invoices/<iid>/void")
def void_invoice(iid):
    require("BillingAdmin")
    inv = get_or_404(db.invoices, iid)
    if inv["status"] not in ("DRAFT", "ISSUED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Invoice cannot be voided")
    inv["status"] = "VOID"
    touch(inv)
    return success(ser_invoice(inv))
