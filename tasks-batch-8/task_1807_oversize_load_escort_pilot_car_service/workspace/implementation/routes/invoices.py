"""Invoice generation, finalize, dispute, adjust, payment, write-off."""

from flask import Blueprint, request

import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_JOB_NOT_FOUND,
    ERR_JOB_INVALID_STATE,
    ERR_INVOICE_NOT_FOUND,
    ERR_INVOICE_INVALID_STATE,
    ERR_ACTIVE_INVOICE_EXISTS,
    ERR_NOT_RESOURCE_OWNER,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_PAYMENT_AMOUNT_MISMATCH,
    ERR_ADJUSTMENT_EXCEEDS_TOTAL,
    raise_err,
)
from middleware import require_roles, ALL_ROLES
from mutate import mark
from response import success_object, paginate
from serializers import ser_invoice, carrier_ytd_billed
from services import calc, cascade
from util import body_json, req_int, req_nonempty_string, new_id

bp = Blueprint("invoices", __name__)

NON_TERMINAL_INVOICE_STATES = ("DRAFT", "FINALIZED", "DISPUTED")


def _get_invoice_or_404(invoice_id):
    inv = db.invoices.get(invoice_id)
    if inv is None:
        raise_err(ERR_INVOICE_NOT_FOUND, f"Invoice {invoice_id} not found")
    return inv


def _compose(job, adjustment_delta):
    """CALC-6 with the job's current inputs; carrier ytd read live."""
    legs = cascade.legs_of_job(job["id"])
    completed = [
        a for leg in legs for a in cascade.assignments_of_leg(leg["id"])
        if a["assignment_status"] == "COMPLETED"
    ]
    closed_delays = [d for d in cascade.delays_of_job(job["id"]) if d["delay_status"] == "CLOSED"]
    settled = [i for i in cascade.incidents_of_job(job["id"]) if i["incident_status"] == "SETTLED"]
    carrier = db.carriers.get(job["carrier_id"])
    ytd = carrier_ytd_billed(carrier) if carrier is not None else 0
    return calc.compose_invoice(job, legs, completed, closed_delays, settled, ytd, adjustment_delta)


@bp.post("/jobs/<id>/invoices")
def generate_invoice(id):
    uid, _role = require_roles("BillingClerk")
    body_json(request)
    job = db.jobs.get(id)
    if job is None:
        raise_err(ERR_JOB_NOT_FOUND, f"Job {id} not found")
    if job["job_status"] not in ("DELIVERED", "CANCELLED"):
        raise_err(ERR_JOB_INVALID_STATE,
                  "Invoices may only be generated for DELIVERED or CANCELLED jobs")
    for inv in cascade.invoices_of_job(job["id"]):
        if inv["invoice_status"] in NON_TERMINAL_INVOICE_STATES:
            raise_err(ERR_ACTIVE_INVOICE_EXISTS, "The job already has a non-terminal invoice")
    legs = cascade.legs_of_job(job["id"])
    has_completed = any(
        a["assignment_status"] == "COMPLETED"
        for leg in legs for a in cascade.assignments_of_leg(leg["id"])
    )
    if job["job_status"] == "CANCELLED" and job["cancel_fee_cents"] == 0 and not has_completed:
        raise_err(ERR_INVALID_REQUEST, "A CANCELLED job with no fee and no completed assignments has nothing to bill")

    comp = _compose(job, 0)
    n = db.now()
    invoice = {
        "id": new_id(),
        "created_at": n,
        "updated_at": n,
        "version": 1,
        "_seq": db.next_seq(),
        "job_id": job["id"],
        "invoice_status": "DRAFT",
        "base_charges_cents": comp["base_charges_cents"],
        "equipment_charges_cents": comp["equipment_charges_cents"],
        "standby_total_cents": comp["standby_total_cents"],
        "subtotal_cents": comp["subtotal_cents"],
        "volume_discount_cents": comp["volume_discount_cents"],
        "fuel_surcharge_cents": comp["fuel_surcharge_cents"],
        "cancellation_fee_cents": comp["cancellation_fee_cents"],
        "incident_chargebacks_cents": comp["incident_chargebacks_cents"],
        "adjustment_delta_cents": 0,
        "total_cents": comp["total_cents"],
        "generated_by_user_id": uid,
        "finalized_at": None,
        "dispute_reason": None,
        "adjustment_note": None,
        "paid_at": None,
    }
    db.invoices[invoice["id"]] = invoice
    return success_object(ser_invoice(invoice), status=201)


@bp.get("/jobs/<id>/invoices")
def list_job_invoices(id):
    require_roles(*ALL_ROLES)
    if id not in db.jobs:
        raise_err(ERR_JOB_NOT_FOUND, f"Job {id} not found")
    rows = cascade.invoices_of_job(id)
    rows.sort(key=lambda i: (i["created_at"], i["_seq"]))
    return paginate(request, [ser_invoice(i) for i in rows])


@bp.get("/invoices/<id>")
def get_invoice(id):
    require_roles(*ALL_ROLES)
    return success_object(ser_invoice(_get_invoice_or_404(id)))


@bp.post("/invoices/<id>/finalize")
def finalize_invoice(id):
    uid, _role = require_roles("BillingClerk")
    body_json(request)
    inv = _get_invoice_or_404(id)
    if inv["invoice_status"] != "DRAFT":
        raise_err(ERR_INVOICE_INVALID_STATE, "Finalization requires the invoice to be DRAFT")
    if inv["generated_by_user_id"] == uid:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "The invoice generator cannot finalize it")
    job = db.jobs.get(inv["job_id"])
    comp = _compose(job, inv["adjustment_delta_cents"])
    for key, value in comp.items():
        inv[key] = value
    inv["finalized_at"] = db.now()
    inv["invoice_status"] = "FINALIZED"
    mark(inv)
    return success_object(ser_invoice(inv))


@bp.post("/invoices/<id>/dispute")
def dispute_invoice(id):
    uid, _role = require_roles("CarrierRep")
    data = body_json(request)
    reason = req_nonempty_string(data, "dispute_reason")
    inv = _get_invoice_or_404(id)
    job = db.jobs.get(inv["job_id"])
    if job is None or job["carrier_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "CarrierRep may only dispute its own carrier's invoices")
    if inv["invoice_status"] != "FINALIZED":
        raise_err(ERR_INVOICE_INVALID_STATE, "Disputing requires the invoice to be FINALIZED")
    inv["dispute_reason"] = reason
    inv["invoice_status"] = "DISPUTED"
    mark(inv)
    return success_object(ser_invoice(inv))


@bp.post("/invoices/<id>/adjust")
def adjust_invoice(id):
    uid, _role = require_roles("BillingClerk")
    data = body_json(request)
    delta = req_int(data, "adjustment_delta_cents")
    note = req_nonempty_string(data, "adjustment_note")
    inv = _get_invoice_or_404(id)
    if inv["invoice_status"] != "DISPUTED":
        raise_err(ERR_INVOICE_INVALID_STATE, "Adjustment requires the invoice to be DISPUTED")
    if inv["generated_by_user_id"] == uid:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "The invoice generator cannot adjust it")
    new_delta = inv["adjustment_delta_cents"] + delta
    new_total = (inv["subtotal_cents"] - inv["volume_discount_cents"]
                 + inv["fuel_surcharge_cents"] + inv["cancellation_fee_cents"]
                 - inv["incident_chargebacks_cents"] + new_delta)
    if new_total < 0:
        raise_err(ERR_ADJUSTMENT_EXCEEDS_TOTAL, "The adjustment would drive total_cents below zero")
    inv["adjustment_delta_cents"] = new_delta
    inv["adjustment_note"] = note
    inv["total_cents"] = new_total
    inv["finalized_at"] = db.now()
    inv["invoice_status"] = "FINALIZED"
    mark(inv)
    return success_object(ser_invoice(inv))


def _close_job_if_delivered(inv):
    job = db.jobs.get(inv["job_id"])
    if job is not None and job["job_status"] == "DELIVERED":
        job["job_status"] = "CLOSED"
        mark(job)


@bp.post("/invoices/<id>/record-payment")
def record_payment(id):
    require_roles("FinanceManager")
    data = body_json(request)
    amount = req_int(data, "amount_cents")
    inv = _get_invoice_or_404(id)
    if inv["invoice_status"] != "FINALIZED":
        raise_err(ERR_INVOICE_INVALID_STATE, "Payment requires the invoice to be FINALIZED")
    if amount != inv["total_cents"]:
        raise_err(ERR_PAYMENT_AMOUNT_MISMATCH, "amount_cents must equal the invoice total exactly")
    inv["paid_at"] = db.now()
    inv["invoice_status"] = "PAID"
    mark(inv)
    _close_job_if_delivered(inv)
    return success_object(ser_invoice(inv))


@bp.post("/invoices/<id>/write-off")
def write_off_invoice(id):
    require_roles("FinanceManager")
    body_json(request)
    inv = _get_invoice_or_404(id)
    if inv["invoice_status"] != "FINALIZED":
        raise_err(ERR_INVOICE_INVALID_STATE, "Write-off requires the invoice to be FINALIZED")
    inv["invoice_status"] = "WRITTEN_OFF"
    mark(inv)
    _close_job_if_delivered(inv)
    return success_object(ser_invoice(inv))
