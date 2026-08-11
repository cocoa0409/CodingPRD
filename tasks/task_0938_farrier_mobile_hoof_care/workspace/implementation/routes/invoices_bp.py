"""Invoices, their immutable line rows, issuing and voiding (PRD 3.9)."""

from flask import Blueprint, request

from core.auth import authenticate
from core.envelope import ok_list, paginate, read_pagination
from core.errors import ApiError
from core.store import db, order_key
from core.timeutil import clock
from domain.lookup import guard_invoice, must
from domain.serializers import serialize_many

from ._common import listing, single

bp = Blueprint("invoices", __name__)

READ_ROLES = ("PlatformAdmin", "BillingClerk", "ClientUser", "Dispatcher")


@bp.get("/invoices")
def list_invoices():
    return listing(
        "invoices",
        {
            "appointment_id": "appointment_id",
            "client_id": "client_id",
            "rate_card_id": "rate_card_id",
            "status": "status",
        },
        READ_ROLES,
    )


@bp.get("/invoices/<invoice_id>")
def read_invoice(invoice_id):
    authenticate(READ_ROLES)
    invoice = must("invoices", invoice_id)
    guard_invoice(invoice)
    return single(invoice)


@bp.get("/invoices/<invoice_id>/lines")
def list_invoice_lines(invoice_id):
    authenticate(READ_ROLES)
    invoice = must("invoices", invoice_id)
    guard_invoice(invoice)
    limit, offset = read_pagination()
    rows = [r for r in db.invoice_lines.values() if r["invoice_id"] == invoice["id"]]
    rows.sort(key=order_key)
    wanted = request.args.get("line_kind")
    if wanted is not None:
        rows = [r for r in rows if r["line_kind"] == wanted]
    page, total = paginate(rows, limit, offset)
    return ok_list(serialize_many(page), total, limit, offset)


@bp.post("/invoices/<invoice_id>/issue")
def issue_invoice(invoice_id):
    authenticate(("BillingClerk",))
    invoice = must("invoices", invoice_id)
    if invoice["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    appointment = db.get("appointments", invoice["appointment_id"])
    # Adjudication of friction 13: "or the appointment is UNROUTED" is read as a
    # test of the ATTACHMENT -- a null route_stop_id -- rather than of the
    # literal status token.  The literal reading would make a LATE-cancellation
    # invoice impossible to issue for ever (its appointment is detached but its
    # status is CANCELLED_LATE), stranding that invoice in DRAFT with no exit
    # but a void, and with it the whole fee-invoice settlement path.
    stop = db.get("route_stops", appointment.get("route_stop_id")) if appointment else None
    if stop is not None and stop["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE")
    invoice["status"] = "ISSUED"
    invoice["issued_on"] = clock.today_iso
    db.touch(invoice)
    return single(invoice)


@bp.post("/invoices/<invoice_id>/void")
def void_invoice(invoice_id):
    authenticate(("BillingClerk",))
    invoice = must("invoices", invoice_id)
    if invoice["status"] == "DRAFT":
        pass
    elif invoice["status"] == "ISSUED" and invoice["paid_cents"] == 0:
        pass
    else:
        raise ApiError("ERR_INVALID_STATE")
    invoice["status"] = "VOID"
    db.touch(invoice)
    appointment = db.get("appointments", invoice["appointment_id"])
    if appointment is not None:
        appointment["billing_status"] = "VOIDED"
        db.touch(appointment)
    return single(invoice)
