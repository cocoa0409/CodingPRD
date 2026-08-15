"""Invoice endpoints (PRD §3.8): provisional snapshot, final settlement."""

from flask import Blueprint

import calc
import db
from errors import (
    ApiError,
    ERR_INVALID_STATE_TRANSITION,
    ERR_INVOICE_ALREADY_OPEN,
    ERR_JOB_NOT_COMPLETE,
)
from middleware import ALL_ROLES, authenticate
from response import ok_object
from routes.common import (
    fk_exists,
    get_body,
    get_or_404,
    list_response,
    req_str,
    ser_plain,
)
from util import touch

bp = Blueprint("invoices", __name__)


@bp.post("/plant/invoices")
def create_invoice():
    authenticate(("BillingClerk",))
    data = get_body()
    fk_exists(db.jobs, data, "job_id")
    job_id = req_str(data, "job_id")
    job = db.jobs[job_id]

    if any(i["job_id"] == job_id and i["status"] != "VOIDED"
           for i in db.invoices.values()):
        raise ApiError(ERR_INVOICE_ALREADY_OPEN, 409,
                       "A non-VOIDED invoice already exists for the job")

    quote = calc.provisional_quote(job)
    rec = db.new_record()
    rec.update({
        "job_id": job_id,
        "variant": "PROVISIONAL",
        "status": "DRAFT",
        "lines": quote["lines"],
        "subtotal_cents": quote["subtotal_cents"],
        "make_ready_waived": quote["make_ready_waived"],
        "make_ready_line_cents": quote["make_ready_line_cents"],
        "minimum_recovery_cents": quote["minimum_recovery_cents"],
        "total_cents": quote["total_cents"],
    })
    db.invoices[rec["id"]] = rec
    return ok_object(ser_plain(rec), 201)


@bp.get("/plant/invoices")
def list_invoices():
    authenticate(ALL_ROLES)
    return list_response(
        db.invoices.values(),
        ser_plain,
        [("job_id", "job_id", "str"), ("status", "status", "str")],
    )


@bp.get("/plant/invoices/<invoiceId>")
def get_invoice(invoiceId):
    authenticate(ALL_ROLES)
    return ok_object(ser_plain(get_or_404(db.invoices, invoiceId)))


@bp.post("/plant/invoices/<invoiceId>/finalize")
def finalize_invoice(invoiceId):
    authenticate(("BillingClerk",))
    rec = get_or_404(db.invoices, invoiceId)
    job = db.jobs[rec["job_id"]]
    if rec["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a DRAFT invoice can be finalized")
    if job["status"] != "COMPLETE":
        raise ApiError(ERR_JOB_NOT_COMPLETE, 409,
                       "Invoice finalization requires a COMPLETE job")

    stock = db.board_stocks.get(job["board_stock_id"]) if job["board_stock_id"] else None
    settlement = calc.final_settlement(
        job, stock, db.finishing_bookings.values(), db.kit_orders.values())

    rec["variant"] = "FINAL"
    rec["status"] = "FINALIZED"
    rec["lines"] = settlement["lines"]
    rec["subtotal_cents"] = settlement["subtotal_cents"]
    rec["make_ready_waived"] = settlement["make_ready_waived"]
    rec["make_ready_line_cents"] = settlement["make_ready_line_cents"]
    rec["minimum_recovery_cents"] = settlement["minimum_recovery_cents"]
    rec["total_cents"] = settlement["total_cents"]
    touch(rec)
    return ok_object(ser_plain(rec))


@bp.post("/plant/invoices/<invoiceId>/void")
def void_invoice(invoiceId):
    authenticate(("BillingClerk",))
    rec = get_or_404(db.invoices, invoiceId)
    if rec["status"] != "FINALIZED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a FINALIZED invoice can be voided")
    rec["status"] = "VOIDED"
    touch(rec)
    return ok_object(ser_plain(rec))


@bp.post("/plant/invoices/<invoiceId>/settle")
def settle_invoice(invoiceId):
    authenticate(("BillingClerk",))
    rec = get_or_404(db.invoices, invoiceId)
    if rec["status"] != "FINALIZED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a FINALIZED invoice can be settled")
    rec["status"] = "SETTLED"
    touch(rec)
    return ok_object(ser_plain(rec))
