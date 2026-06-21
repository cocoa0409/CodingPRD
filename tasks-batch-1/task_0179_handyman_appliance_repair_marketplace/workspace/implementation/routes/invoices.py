"""Invoice create / fetch / list / issue / pay (PRD §3.7).

Invoice state machine: DRAFT -> ISSUED -> PAID -> REFUNDED, plus VOID.
"""
from flask import Blueprint, request, g

from db import store
from errors import ApiError
from middleware import require_role
from models import common, touch, serialize, INVOICE_FIELDS
from response import object_response, array_response
from services import pricing
from services.lookup import (
    require_body, require_int, get_or_404, paginate, sorted_by_creation,
)

bp = Blueprint("invoices", __name__)


@bp.post("/jobs/<jid>/invoices")
@require_role({"Pro"})
def create_invoice(jid):
    job = get_or_404(store.jobs, jid)
    if g.user_id != job.get("pro_id"):
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Acting Pro is not the job's Pro")
    if job["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Invoice only for IN_PROGRESS jobs")

    invoice = {
        "job_id": jid,
        "labor_subtotal_cents": 0,
        "parts_subtotal_cents": 0,
        "trip_fee_cents": 0,
        "total_cents": 0,
        "amount_paid_cents": 0,
        "refunded_cents": 0,
        "balance_due_cents": 0,
        "status": "DRAFT",
    }
    common(invoice)
    store.invoices[invoice["id"]] = invoice
    return object_response(serialize(invoice, INVOICE_FIELDS), status=201)


@bp.get("/jobs/<jid>/invoices")
@require_role({"PlatformAdmin", "Customer", "Pro", "Dispatcher"})
def list_job_invoices(jid):
    get_or_404(store.jobs, jid)
    items = [i for i in store.invoices.values() if i["job_id"] == jid]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(i, INVOICE_FIELDS) for i in page],
                          limit, offset, total)


@bp.get("/invoices/<iid>")
@require_role({"PlatformAdmin", "Customer", "Pro", "Dispatcher"})
def get_invoice(iid):
    invoice = get_or_404(store.invoices, iid)
    return object_response(serialize(invoice, INVOICE_FIELDS))


@bp.post("/invoices/<iid>/issue")
@require_role({"Pro"})
def issue_invoice(iid):
    invoice = get_or_404(store.invoices, iid)
    job = store.jobs[invoice["job_id"]]
    if g.user_id != job.get("pro_id"):
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Acting Pro is not the job's Pro")
    if invoice["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Issue only from DRAFT")
    if job["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Job must be IN_PROGRESS to issue")

    category = store.service_categories[job["category_id"]]
    labor_lines = [l for l in store.labor_lines.values() if l["job_id"] == job["id"]]
    part_lines = [p for p in store.part_lines.values() if p["job_id"] == job["id"]]

    # HOURLY must carry labor hours before issue; FLAT must carry none.
    if category["pricing_model"] == "HOURLY":
        if not labor_lines:
            raise ApiError("ERR_PRICING_MODEL_MISMATCH",
                           "HOURLY invoice requires labor lines before issuing")
    else:  # FLAT
        if labor_lines:
            raise ApiError("ERR_PRICING_MODEL_MISMATCH",
                           "FLAT category must not carry labor lines")

    pro = store.pros[job["pro_id"]]
    totals = pricing.compute_invoice_totals(job, category, pro, labor_lines, part_lines)
    invoice.update(totals)
    invoice["status"] = "ISSUED"
    invoice["amount_paid_cents"] = 0
    invoice["refunded_cents"] = 0
    pricing.reconcile_balance(invoice)
    touch(invoice)
    return object_response(serialize(invoice, INVOICE_FIELDS))


def _v_pay(body):
    return {"amount": require_int(body, "amount_cents", minimum=0)}


@bp.post("/invoices/<iid>/pay")
@require_role({"Customer"}, validate=_v_pay)
def pay_invoice(iid):
    amount = g.validated["amount"]
    invoice = get_or_404(store.invoices, iid)
    job = store.jobs[invoice["job_id"]]
    # ownership: the paying Customer must own the job.
    if g.user_id != job["customer_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Customer does not own this invoice's job")
    if invoice["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Pay only from ISSUED")

    # full payment only.
    if amount != invoice["balance_due_cents"]:
        raise ApiError("ERR_PARTIAL_PAYMENT", "Payment must equal balance_due exactly")

    invoice["amount_paid_cents"] += amount
    pricing.reconcile_balance(invoice)
    invoice["status"] = "PAID"
    touch(invoice)
    return object_response(serialize(invoice, INVOICE_FIELDS))
