"""Per-job billing: invoice issuance, payments, void (PRD §3.4)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVOICE_HAS_PAYMENTS,
    ERR_INVOICE_NOT_OPEN,
    ERR_JOB_ALREADY_BILLED,
    ERR_JOB_NOT_COMPLETED,
    ERR_OVERPAYMENT,
    ERR_STALE_INVOICE_VERSION,
)
from middleware import require
from response import ok_array, ok_object
from services.common import (
    by_created_asc,
    get_json_body,
    init_common,
    init_ledger,
    paginate,
    parse_pagination,
    public,
    public_list,
    require_enum,
    require_int,
    touch,
)
from services.calculations import compute_settled_price
from services.computed import (
    addons_of_job,
    recompute_amount_paid,
    recompute_wallet_credit,
    rooms_of_job,
)
from services.lookups import get_invoice, get_job

bp = Blueprint("billing", __name__)

PAYMENT_METHODS = {"CARD", "CASH", "CHECK"}


# ---------------------------------------------------------------------------
# Issue per-job invoice (UNBILLED -> INVOICED)
# ---------------------------------------------------------------------------
@bp.post("/cleaning-jobs/<jid>/invoice")
def issue_invoice(jid):
    require(["Billing", "ServiceManager"])
    job = get_job(jid)

    # lifecycle must be COMPLETED -> ERR_JOB_NOT_COMPLETED
    if job["lifecycle_status"] != "COMPLETED":
        raise APIError(ERR_JOB_NOT_COMPLETED, 409, "Job is not COMPLETED")

    # no existing OPEN/SETTLED invoice for this job -> ERR_JOB_ALREADY_BILLED
    for inv in db.invoices.values():
        if inv["cleaning_job_id"] == jid and inv["status"] in ("OPEN", "SETTLED"):
            raise APIError(ERR_JOB_ALREADY_BILLED, 409, "Job already has an active invoice")

    catalog = db.service_catalogs[job["service_catalog_id"]]
    plan = db.recurring_plans.get(job["recurring_plan_id"]) if job["recurring_plan_id"] else None
    # replay rooms/add-ons in created_at ASC order
    rooms_chrono = by_created_asc(rooms_of_job(jid))
    addons_chrono = by_created_asc(addons_of_job(jid))

    settled = compute_settled_price(catalog, job, rooms_chrono, addons_chrono, plan)
    job["settled_price_cents"] = settled

    customer = db.customers[job["customer_id"]]
    recompute_wallet_credit(customer)
    amount_due = settled
    wallet_applied = min(customer["wallet_credit_cents"], amount_due)
    net_payable = amount_due - wallet_applied

    invoice = init_common({
        "cleaning_job_id": jid,
        "amount_due_cents": amount_due,
        "wallet_applied_cents": wallet_applied,
        "net_payable_cents": net_payable,
        "amount_paid_cents": 0,
        "status": "OPEN",
    })
    db.invoices[invoice["id"]] = invoice

    # cascade hop: invoice issuance -> wallet debit (if any applied)
    if wallet_applied > 0:
        entry = init_ledger({
            "customer_id": customer["id"],
            "delta_cents": -wallet_applied,
            "reason": "INVOICE_APPLIED",
            "cleaning_job_id": jid,
        })
        db.wallet_ledger_entries[entry["id"]] = entry
        recompute_wallet_credit(customer)

    # set job.invoice_id and billing_status = INVOICED (job mutation)
    job["invoice_id"] = invoice["id"]
    job["billing_status"] = "INVOICED"
    touch(job)

    return ok_object(public(invoice), 201)


@bp.get("/invoices/<iid>")
def get_invoice_ep(iid):
    require(["Customer", "ServiceManager", "Billing"])
    inv = get_invoice(iid)
    return ok_object(public(inv), 200)


@bp.get("/cleaning-jobs/<jid>/invoices")
def list_job_invoices(jid):
    require(["Customer", "ServiceManager", "Billing"])
    get_job(jid)
    limit, offset = parse_pagination()
    rows = [i for i in db.invoices.values() if i["cleaning_job_id"] == jid]
    rows = by_created_asc(rows)
    window, total = paginate(rows, limit, offset)
    return ok_array(public_list(window), limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Record a payment (OCC on invoice)
# ---------------------------------------------------------------------------
@bp.post("/invoices/<iid>/payments")
def record_payment(iid):
    require(["Billing", "ServiceManager"])
    inv = get_invoice(iid)
    body = get_json_body()
    amount_cents = require_int(body, "amount_cents", minimum=1)
    method = require_enum(body, "method", PAYMENT_METHODS)
    expected_invoice_version = require_int(body, "expected_invoice_version")

    # state gate (priority 6): invoice must be OPEN -> ERR_INVOICE_NOT_OPEN
    if inv["status"] != "OPEN":
        raise APIError(ERR_INVOICE_NOT_OPEN, 409, "Invoice is not OPEN")

    # overpayment guard (priority 13): amount <= net_payable - amount_paid
    remaining = inv["net_payable_cents"] - inv["amount_paid_cents"]
    if amount_cents > remaining:
        raise APIError(ERR_OVERPAYMENT, 402, "Payment exceeds remaining net balance")

    # OCC (priority 15): expected_invoice_version must match live version
    if expected_invoice_version != inv["version"]:
        raise APIError(ERR_STALE_INVOICE_VERSION, 412, "Stale invoice version")

    payment = init_common({
        "invoice_id": iid,
        "amount_cents": amount_cents,
        "method": method,
        "status": "APPLIED",
    })
    db.payments[payment["id"]] = payment

    # recompute amount_paid; bump invoice version
    recompute_amount_paid(inv)
    touch(inv)

    # settlement: cumulative APPLIED >= net_payable -> OPEN -> SETTLED, job PAID
    if inv["amount_paid_cents"] >= inv["net_payable_cents"]:
        inv["status"] = "SETTLED"
        touch(inv)
        job = db.cleaning_jobs.get(inv["cleaning_job_id"])
        if job is not None:
            job["billing_status"] = "PAID"
            touch(job)

    return ok_object(public(payment), 201)


@bp.get("/invoices/<iid>/payments")
def list_payments(iid):
    require(["Customer", "ServiceManager", "Billing"])
    get_invoice(iid)
    limit, offset = parse_pagination()
    rows = [p for p in db.payments.values() if p["invoice_id"] == iid]
    rows = by_created_asc(rows)
    window, total = paginate(rows, limit, offset)
    return ok_array(public_list(window), limit, offset, total, 200)


# ---------------------------------------------------------------------------
# Void an unpaid invoice (compensation)
# ---------------------------------------------------------------------------
@bp.post("/invoices/<iid>/void")
def void_invoice(iid):
    require(["Billing", "ServiceManager"])
    inv = get_invoice(iid)

    # state gate (priority 6): invoice must be OPEN -> ERR_INVOICE_NOT_OPEN
    if inv["status"] != "OPEN":
        raise APIError(ERR_INVOICE_NOT_OPEN, 409, "Invoice is not OPEN")

    # void requires amount_paid == 0 (priority 14) -> ERR_INVOICE_HAS_PAYMENTS
    if inv["amount_paid_cents"] != 0:
        raise APIError(ERR_INVOICE_HAS_PAYMENTS, 409, "Invoice has applied payments")

    inv["status"] = "VOID"
    touch(inv)

    # refund any wallet that was applied at issuance
    job = db.cleaning_jobs.get(inv["cleaning_job_id"])
    if inv["wallet_applied_cents"] > 0 and job is not None:
        customer = db.customers[job["customer_id"]]
        entry = init_ledger({
            "customer_id": customer["id"],
            "delta_cents": inv["wallet_applied_cents"],
            "reason": "INVOICE_REFUND",
            "cleaning_job_id": job["id"],
        })
        db.wallet_ledger_entries[entry["id"]] = entry
        recompute_wallet_credit(customer)

    # compensation: reset job billing to UNBILLED and clear invoice_id
    if job is not None:
        job["billing_status"] = "UNBILLED"
        job["invoice_id"] = None
        touch(job)

    return ok_object(public(inv), 200)
