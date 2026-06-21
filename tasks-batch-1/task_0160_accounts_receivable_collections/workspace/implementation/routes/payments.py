"""Payment, application, auto-apply, and reversal endpoints (PRD §3.3)."""
from flask import Blueprint, request

import db
from errors import (
    err, ERR_INVALID_STATE, ERR_CUSTOMER_MISMATCH, ERR_OVER_APPLICATION,
    ERR_APPLY_EXCEEDS_INVOICE,
)
from middleware import get_identity, authorize
from response import success, list_response
from services import domain, lookup
from services.common import (
    stamp_create, touch, get_json_body, require_str, require_int,
    parse_pagination, paginate,
)
from timeutil import parse_iso_ms

bp = Blueprint("payments", __name__)


def _recompute_payment_status(payment):
    if payment["applied_cents"] == 0:
        payment["status"] = "UNAPPLIED"
    elif payment["unapplied_cents"] == 0:
        payment["status"] = "FULLY_APPLIED"
    else:
        payment["status"] = "PARTIALLY_APPLIED"


@bp.route("/ar/payments", methods=["POST"])
def create_payment():
    _, role = get_identity()
    authorize(role, ["AR_CLERK", "AR_MANAGER"])
    body = get_json_body()
    customer_id = require_str(body, "customer_id")
    customer = lookup.get_customer(customer_id)
    amount = require_int(body, "amount_cents", minimum=1)
    received_at = require_str(body, "received_at")
    received_at_ms = parse_iso_ms(received_at)  # validate format

    p = {
        "customer_id": customer_id,
        "amount_cents": amount,
        "received_at": received_at,
        "received_at_ms": received_at_ms,
        "applied_cents": 0,
        "unapplied_cents": amount,
        "status": "UNAPPLIED",
    }
    stamp_create(p)
    db.payments[p["id"]] = p
    return success(domain.serialize_payment(p), status=201)


@bp.route("/ar/payments/<pid>", methods=["GET"])
def get_payment(pid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "AR_CLERK", "AUDITOR"])
    p = lookup.get_payment(pid)
    return success(domain.serialize_payment(p), status=200)


@bp.route("/ar/payments", methods=["GET"])
def list_payments():
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "AR_CLERK", "AUDITOR"])
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    items = list(db.payments.values())
    if customer_id is not None:
        items = [p for p in items if p["customer_id"] == customer_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([domain.serialize_payment(p) for p in page], limit, offset, total)


def _apply_one(payment, invoice, applied_cents, settle_in_full):
    """Create one PaymentApplication and cascade. Caller has already validated
    state/customer-match/ceilings. Returns the application record."""
    prior_balance = invoice["balance_cents"]
    short_pay = 0
    if settle_in_full:
        # settle to PAID; gap booked as short pay
        short_pay = invoice["balance_cents"] - applied_cents
        invoice["balance_cents"] = 0
        invoice["status"] = "PAID"
    else:
        invoice["balance_cents"] = invoice["balance_cents"] - applied_cents
        if invoice["balance_cents"] == 0:
            invoice["status"] = "PAID"
        else:
            invoice["status"] = "PARTIAL"
    touch(invoice)

    app = {
        "payment_id": payment["id"],
        "invoice_id": invoice["id"],
        "applied_cents": applied_cents,
        "short_pay_cents": short_pay,
        "reversed": False,
    }
    stamp_create(app)
    db.payment_applications[app["id"]] = app

    payment["applied_cents"] += applied_cents
    payment["unapplied_cents"] = payment["amount_cents"] - payment["applied_cents"]
    _recompute_payment_status(payment)
    touch(payment)

    customer = db.customers.get(invoice["customer_id"])
    if customer is not None:
        domain.recompute_customer(customer, recompute_stage=True)
    return app


@bp.route("/ar/payments/<pid>/applications", methods=["POST"])
def apply_payment(pid):
    _, role = get_identity()
    authorize(role, ["AR_CLERK"])
    payment = lookup.get_payment(pid)
    body = get_json_body()
    invoice_id = require_str(body, "invoice_id")
    invoice = lookup.get_invoice(invoice_id)
    applied_cents = require_int(body, "applied_cents", minimum=1)
    settle_in_full = bool(body.get("settle_in_full", False))

    # state (priority 6): payment must be UNAPPLIED or PARTIALLY_APPLIED;
    # invoice must be OPEN or PARTIAL.
    if payment["status"] not in ("UNAPPLIED", "PARTIALLY_APPLIED"):
        raise err(ERR_INVALID_STATE, "payment not applicable")
    if invoice["status"] not in ("OPEN", "PARTIAL"):
        raise err(ERR_INVALID_STATE, "invoice not in an applicable state")

    # customer-match (priority 10)
    if payment["customer_id"] != invoice["customer_id"]:
        raise err(ERR_CUSTOMER_MISMATCH, "payment and invoice belong to different customers")

    # over-application (priority 14)
    if applied_cents > payment["unapplied_cents"]:
        raise err(ERR_OVER_APPLICATION, "applied_cents exceeds unapplied payment")

    # apply-exceeds-invoice (priority 15)
    dun = domain.dunnable(invoice)
    if settle_in_full:
        if applied_cents > dun:
            raise err(ERR_APPLY_EXCEEDS_INVOICE, "applied_cents exceeds invoice dunnable balance")
    else:
        if applied_cents > dun:
            raise err(ERR_APPLY_EXCEEDS_INVOICE, "applied_cents exceeds invoice dunnable balance")

    app = _apply_one(payment, invoice, applied_cents, settle_in_full)
    return success(domain.serialize_application(app), status=201)


@bp.route("/ar/payments/<pid>/auto-apply", methods=["POST"])
def auto_apply(pid):
    _, role = get_identity()
    authorize(role, ["AR_CLERK"])
    payment = lookup.get_payment(pid)

    customer_id = payment["customer_id"]
    # candidates: customer's OPEN/PARTIAL invoices, oldest-aging first.
    candidates = [
        iv for iv in db.invoices.values()
        if iv["customer_id"] == customer_id and iv["status"] in ("OPEN", "PARTIAL")
    ]

    def sort_key(iv):
        bucket = domain.aging_bucket(iv, "due")
        # most overdue bucket first => DESC by aging index => negate index
        aging_rank = -domain.AGING_ORDER.index(bucket)
        return (aging_rank, iv["due_date_ms"], iv["created_at"])

    candidates.sort(key=sort_key)

    remaining = payment["unapplied_cents"]
    for iv in candidates:
        if remaining == 0:
            break
        dun = domain.dunnable(iv)
        if dun <= 0:
            continue
        take = min(remaining, dun)
        # straight partial/settle application (no short-pay flag in waterfall)
        _apply_one(payment, iv, take, settle_in_full=False)
        remaining -= take

    return success(domain.serialize_payment(payment), status=200)


@bp.route("/ar/payments/<pid>/applications", methods=["GET"])
def list_applications(pid):
    _, role = get_identity()
    authorize(role, ["AR_MANAGER", "AR_CLERK", "AUDITOR"])
    lookup.get_payment(pid)
    limit, offset = parse_pagination()
    items = [a for a in db.payment_applications.values() if a["payment_id"] == pid]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return list_response([domain.serialize_application(a) for a in page], limit, offset, total)


@bp.route("/ar/payments/<pid>/applications/<aid>/reverse", methods=["POST"])
def reverse_application(pid, aid):
    _, role = get_identity()
    authorize(role, ["AR_CLERK"])
    payment = lookup.get_payment(pid)
    app = lookup.get_application(aid)
    # nested ownership: application must belong to the payment in the path.
    if app["payment_id"] != pid:
        raise err(ERR_INVALID_STATE, "application does not belong to this payment")
    # state (priority 6): cannot reverse an already-reversed application.
    if app["reversed"]:
        raise err(ERR_INVALID_STATE, "application already reversed")

    invoice = db.invoices.get(app["invoice_id"])
    applied = app["applied_cents"]

    app["reversed"] = True
    touch(app)

    if invoice is not None:
        # Restore the invoice balance by the application's applied_cents. The
        # short-pay gap (if any) is also restored, because reversal returns the
        # ledger to its pre-application state (total_open_balance invariant).
        if app["short_pay_cents"]:
            invoice["balance_cents"] += applied + app["short_pay_cents"]
        else:
            invoice["balance_cents"] += applied
        # revert status if it had reached PAID/PARTIAL
        if invoice["status"] in ("PAID", "PARTIAL"):
            if invoice["balance_cents"] >= invoice["face_amount_cents"]:
                invoice["status"] = "OPEN"
            else:
                invoice["status"] = "PARTIAL"
        touch(invoice)

    payment["applied_cents"] -= applied
    payment["unapplied_cents"] = payment["amount_cents"] - payment["applied_cents"]
    _recompute_payment_status(payment)
    touch(payment)

    if invoice is not None:
        customer = db.customers.get(invoice["customer_id"])
        if customer is not None:
            domain.recompute_customer(customer, recompute_stage=True)

    return success(domain.serialize_application(app), status=200)
