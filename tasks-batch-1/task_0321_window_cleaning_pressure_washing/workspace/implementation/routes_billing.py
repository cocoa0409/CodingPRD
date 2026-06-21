"""Invoice and ReCleanRequest endpoints (billing dimension)."""
from flask import Blueprint, request

import calc
import db
from auth import require_roles
from errors import err
from helpers import (
    body, get_or_404, paginate, pagination_params, post_ledger, req_str,
)
from response import success, list_success
from serialize import public, public_list
from visit_ops import generate_visit, requires_high_rise, requires_soft_wash

bp = Blueprint("billing", __name__)


# ---------------------------------------------------------------- Invoices
@bp.post("/invoices")
def create_invoice():
    require_roles({"Billing"})
    data = body()
    visit_id = req_str(data, "visit_id")
    visit = get_or_404(db.visits, visit_id)
    agreement = db.agreements.get(visit["agreement_id"])
    if agreement is None:
        raise err("ERR_REFERENTIAL_MISMATCH", "visit agreement does not resolve")

    # state guard precedes duplicate-invoice guard (§3.9 priority order).
    if visit["schedule_status"] != "COMPLETED":
        raise err("ERR_VISIT_NOT_COMPLETED", "Visit is not COMPLETED")
    # billing_status must be UNBILLED (generic state guard).
    if visit["billing_status"] != "UNBILLED":
        # A WAIVED/INVOICED/PAID visit cannot be (re)invoiced.
        if any(i["visit_id"] == visit_id and i["status"] != "VOID" for i in db.invoices.values()):
            raise err("ERR_DUPLICATE_INVOICE", "An invoice already exists for this visit")
        raise err("ERR_INVALID_STATE", "Visit billing_status is not UNBILLED")
    # duplicate-invoice guard
    if any(i["visit_id"] == visit_id and i["status"] != "VOID" for i in db.invoices.values()):
        raise err("ERR_DUPLICATE_INVOICE", "An invoice already exists for this visit")

    account_id = agreement["account_id"]
    amount = visit["charge_amount_cents"]

    # waterfall: consume HELD deposits oldest-first.
    held = [
        d for d in db.deposits.values()
        if d["agreement_id"] == agreement["id"] and d["status"] == "HELD"
    ]
    held.sort(key=lambda d: d["_seq"])
    remaining = amount
    applied = 0
    fully_consumed = []
    for dep in held:
        if remaining == 0:
            break
        take = min(dep["amount_cents"], remaining)
        applied += take
        remaining -= take
        if take == dep["amount_cents"]:
            fully_consumed.append(dep)
    deposit_applied = applied
    net_due = amount - deposit_applied

    inv = db.new_record(db.invoices, {
        "account_id": account_id,
        "visit_id": visit_id,
        "amount_cents": amount,
        "deposit_applied_cents": deposit_applied,
        "net_due_cents": net_due,
        "status": "ISSUED",
    })

    # billing_status UNBILLED -> INVOICED.
    visit["billing_status"] = "INVOICED"
    db.touch(visit)

    # Mark fully-consumed deposits APPLIED.
    for dep in fully_consumed:
        dep["status"] = "APPLIED"
        db.touch(dep)

    # Ledger: INVOICE debit (+net_due) and, if applied, DEPOSIT credit.
    post_ledger(account_id, "INVOICE", inv["id"], net_due)
    if deposit_applied > 0:
        post_ledger(account_id, "DEPOSIT", inv["id"], -deposit_applied)
    return success(public(inv), status=201)


@bp.get("/invoices")
def list_invoices():
    require_roles({"Billing", "Customer"})
    limit, offset = pagination_params()
    visit_id = request.args.get("visit_id")
    account_id = request.args.get("account_id")
    rows = list(db.invoices.values())
    if visit_id is not None:
        rows = [i for i in rows if i["visit_id"] == visit_id]
    if account_id is not None:
        rows = [i for i in rows if i["account_id"] == account_id]
    page, total = paginate(rows, limit, offset)
    return list_success(public_list(page), total, limit, offset)


@bp.get("/invoices/<rid>")
def read_invoice(rid):
    require_roles({"Billing", "Customer"})
    rec = get_or_404(db.invoices, rid)
    return success(public(rec))


@bp.post("/invoices/<rid>/pay")
def pay_invoice(rid):
    require_roles({"Billing"})
    inv = get_or_404(db.invoices, rid)
    if inv["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "Invoice is not ISSUED")
    visit = db.visits.get(inv["visit_id"])
    if visit is None or visit["billing_status"] != "INVOICED":
        raise err("ERR_INVALID_STATE", "Visit billing_status is not INVOICED")
    inv["status"] = "PAID"
    db.touch(inv)
    visit["billing_status"] = "PAID"
    db.touch(visit)
    # PAYMENT credit (-net_due).
    post_ledger(inv["account_id"], "PAYMENT", inv["id"], -inv["net_due_cents"])
    return success(public(inv))


# ---------------------------------------------------------------- ReClean
@bp.post("/reclean-requests")
def create_reclean():
    require_roles({"Customer"})
    data = body()
    visit_id = req_str(data, "visit_id")
    reason = req_str(data, "reason")
    visit = get_or_404(db.visits, visit_id)
    if visit["schedule_status"] != "COMPLETED":
        raise err("ERR_VISIT_NOT_COMPLETED", "Visit is not COMPLETED")
    rec = db.new_record(db.reclean_requests, {
        "visit_id": visit_id,
        "reason": reason,
        "remedy_visit_id": None,
        "credit_cents": 0,
        "status": "REQUESTED",
    })
    return success(public(rec), status=201)


@bp.get("/reclean-requests/<rid>")
def read_reclean(rid):
    require_roles({"Customer", "Billing"})
    rec = get_or_404(db.reclean_requests, rid)
    return success(public(rec))


@bp.post("/reclean-requests/<rid>/approve")
def approve_reclean(rid):
    require_roles({"Billing"})
    rec = get_or_404(db.reclean_requests, rid)
    if rec["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Re-clean request is not REQUESTED")
    visit = db.visits.get(rec["visit_id"])
    if visit is None or visit["schedule_status"] != "COMPLETED":
        raise err("ERR_VISIT_NOT_COMPLETED", "Target visit is not COMPLETED")
    agreement = db.agreements.get(visit["agreement_id"])
    account_id = agreement["account_id"]

    # goodwill credit keyed on AFTER-photo doc density.
    after_n = sum(
        1 for p in db.visit_photos.values()
        if p["visit_id"] == visit["id"] and p["phase"] == "AFTER"
    )
    credit = calc.reclean_credit(visit["charge_amount_cents"], after_n)
    rec["credit_cents"] = credit
    rec["status"] = "APPROVED"

    # RECLEAN_CREDIT ledger entry (signed -credit).
    post_ledger(account_id, "RECLEAN_CREDIT", rec["id"], -credit)

    # Unwind billing of the unsatisfactory visit.
    if visit["billing_status"] == "UNBILLED":
        visit["billing_status"] = "WAIVED"
        db.touch(visit)
    elif visit["billing_status"] == "INVOICED":
        for inv in db.invoices.values():
            if inv["visit_id"] == visit["id"] and inv["status"] == "ISSUED":
                inv["status"] = "VOID"
                db.touch(inv)
                # reverse the INVOICE debit
                post_ledger(account_id, "INVOICE", inv["id"], -inv["net_due_cents"])

    # Synthesize a no-charge remedy visit (UNSCHEDULED) on the same agreement.
    prop = db.properties.get(agreement["property_id"])
    quote = db.quotes.get(agreement["quote_id"])
    remedy = generate_visit(
        agreement, visit["planned_date"], visit["window_start_min"],
        visit["window_end_min"], requires_soft_wash(quote), requires_high_rise(prop),
    )
    rec["remedy_visit_id"] = remedy["id"]
    db.touch(rec)
    return success(public(rec))


@bp.post("/reclean-requests/<rid>/deny")
def deny_reclean(rid):
    require_roles({"Billing"})
    rec = get_or_404(db.reclean_requests, rid)
    if rec["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Re-clean request is not REQUESTED")
    rec["status"] = "DENIED"
    db.touch(rec)
    return success(public(rec))
