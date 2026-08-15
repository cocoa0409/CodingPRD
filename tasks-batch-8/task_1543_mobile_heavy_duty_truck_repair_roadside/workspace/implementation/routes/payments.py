"""Payment endpoints: post with waterfall allocation, void."""
from flask import Blueprint, request

from db import store, new_record, touch
from errors import (ApiError, err_not_found, err_invalid_state)
from middleware import auth
from response import success
from serializers import serialize
from services.cascades import append_event, close_call, wall_now
from services.pricing import waterfall_allocate
from util import Field, validate_body, parse_pagination, paginate

bp = Blueprint("payments", __name__)

METHODS = {"CHECK", "CARD", "ACH", "FLEET_ACCOUNT"}
READ_ROLES = ["OpsAdmin", "BillingClerk"]


def _get_payment(payment_id):
    p = store.payments.get(payment_id)
    if p is None:
        raise err_not_found("Payment not found")
    return p


def _recompute_invoice_payment_state(inv):
    paid = sum(p["amount_cents"] for p in store.payments.values()
               if p["invoice_id"] == inv["id"] and p["status"] == "POSTED")
    inv["amount_paid_cents"] = paid
    inv["outstanding_cents"] = inv["total_cents"] - paid
    if inv["payment_status"] == "WRITTEN_OFF":
        return
    if inv["outstanding_cents"] <= 0:
        inv["payment_status"] = "PAID"
    elif paid > 0:
        inv["payment_status"] = "PARTIALLY_PAID"
    else:
        inv["payment_status"] = "UNPAID"


@bp.route("/roadside/invoices/<invoiceId>/payments", methods=["POST"])
def create_payment(invoiceId):
    uid, role = auth(["BillingClerk"])
    inv = store.invoices.get(invoiceId)
    if inv is None:
        raise err_not_found("Invoice not found")
    vals = validate_body(request.get_json(silent=True), [
        Field("amount_cents", "int", required=True, min_val=1),
        Field("method", "enum", required=True, enum=METHODS),
        Field("received_at", "datetime"),
    ])
    if inv["issue_status"] == "VOID":
        raise err_invalid_state("Cannot pay a VOID invoice")
    if inv["payment_status"] in ("PAID", "WRITTEN_OFF"):
        raise err_invalid_state("Invoice carries no collectible balance")
    if vals["amount_cents"] > inv["outstanding_cents"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE",
                       "Payment amount exceeds invoice outstanding_cents", 422)
    allocation = waterfall_allocate(inv, vals["amount_cents"])
    rec = new_record()
    now = wall_now()
    rec.update({
        "_created": now, "_updated": now,
        "invoice_id": inv["id"],
        "amount_cents": vals["amount_cents"],
        "method": vals["method"],
        "received_at": vals.get("received_at") or store.clock,
        "allocation_json": allocation,
        "status": "POSTED",
        "void_reason": None,
    })
    store.payments[rec["id"]] = rec
    _recompute_invoice_payment_state(inv)
    touch(inv, wall_now())
    call = store.service_calls.get(inv["service_call_id"])
    if call is not None:
        append_event(call["id"], "PAYMENT_POSTED", role, uid)
        if inv["payment_status"] == "PAID":
            close_call(call)
    return success(serialize("payment", rec), status=201)


@bp.route("/roadside/payments/<paymentId>", methods=["GET"])
def get_payment(paymentId):
    auth(READ_ROLES)
    return success(serialize("payment", _get_payment(paymentId)))


@bp.route("/roadside/payments", methods=["GET"])
def list_payments():
    auth(READ_ROLES)
    limit, offset = parse_pagination(request.args)
    inv_f = request.args.get("invoice_id")
    status_f = request.args.get("status")
    items = sorted(store.payments.values(), key=lambda r: r["_seq"])
    if inv_f is not None:
        items = [p for p in items if p["invoice_id"] == inv_f]
    if status_f is not None:
        items = [p for p in items if p["status"] == status_f]
    page, total, has_more = paginate(items, limit, offset)
    return success([serialize("payment", p) for p in page],
                   response_type="array",
                   pagination={"limit": limit, "offset": offset,
                               "total_count": total, "has_more": has_more})


@bp.route("/roadside/payments/<paymentId>/void", methods=["POST"])
def void_payment(paymentId):
    uid, role = auth(["BillingClerk", "OpsAdmin"])
    payment = _get_payment(paymentId)
    vals = validate_body(request.get_json(silent=True), [
        Field("reason", "string", required=True),
    ])
    if payment["status"] != "POSTED":
        raise err_invalid_state("Only a POSTED payment can be voided")
    payment["status"] = "VOID"
    payment["void_reason"] = vals["reason"]
    touch(payment, wall_now())
    inv = store.invoices.get(payment["invoice_id"])
    if inv is not None:
        _recompute_invoice_payment_state(inv)
        touch(inv, wall_now())
        call = store.service_calls.get(inv["service_call_id"])
        if call is not None:
            append_event(call["id"], "PAYMENT_VOIDED", role, uid)
    return success(serialize("payment", payment))
