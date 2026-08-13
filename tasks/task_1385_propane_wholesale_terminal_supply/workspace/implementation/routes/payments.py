"""Dealer payment endpoints: FIFO application + NSF returns."""
from flask import Blueprint

import db
import middleware as mw
import response as resp
import serializers as ser
import services as svc
from errors import (
    err_not_found,
    err_referenced_not_found,
    err_invalid_request,
    err_dealer_mismatch,
    err_overpayment,
    err_payment_already_returned,
)

bp = Blueprint("payments", __name__)

READ_ROLES = ["CreditManager", "DealerUser"]
WRITE_ROLES = ["CreditManager"]
METHODS = {"ACH", "CHECK", "WIRE"}
PAYMENT_STATES = {"POSTED", "RETURNED"}


@bp.route("/dealer-payments", methods=["POST"])
def create_payment():
    caller = mw.authenticate()
    mw.authorize(caller, WRITE_ROLES)
    body = mw.get_json_body(required=True)
    dealer_id = mw.req_string(body, "dealer_id")
    amount_cents = mw.req_int(body, "amount_cents")
    method = mw.req_enum(body, "method", METHODS)

    dealer = db.dealers.get(dealer_id)
    if dealer is None:
        raise err_referenced_not_found("dealer_id does not resolve")

    if amount_cents <= 0:
        raise err_invalid_request("amount_cents must be > 0")

    # overpayment cap: payment must not exceed the dealer's total open invoice balance
    open_invoices = [
        o
        for o in db.delivery_orders.values()
        if o["dealer_id"] == dealer_id and o["invoice_status"] == "OPEN"
    ]
    total_open = sum(o["open_balance_cents"] or 0 for o in open_invoices)
    if amount_cents > total_open:
        raise err_overpayment()

    # FIFO application: invoiced_at ASC, tie created_at (_seq) ASC
    open_invoices.sort(key=lambda o: (o["invoiced_at"], o["_seq"]))
    applications = []
    remaining = amount_cents
    for o in open_invoices:
        if remaining == 0:
            break
        sl = min(remaining, o["open_balance_cents"])
        o["open_balance_cents"] -= sl
        applications.append({"order_id": o["id"], "amount_cents": sl})
        if o["open_balance_cents"] == 0:
            o["invoice_status"] = "PAID"
        svc.touch(o)
        remaining -= sl

    now = svc.stamp_now()
    p = {
        "id": db.new_id(),
        "dealer_id": dealer_id,
        "amount_cents": amount_cents,
        "method": method,
        "status": "POSTED",
        "applications": applications,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.dealer_payments[p["id"]] = p
    return resp.created(ser.serialize_payment(p))


@bp.route("/dealer-payments/<pid>", methods=["GET"])
def get_payment(pid):
    caller = mw.authenticate()
    mw.authorize(caller, READ_ROLES)
    p = db.dealer_payments.get(pid)
    if p is None:
        raise err_not_found()
    if caller["role"] == "DealerUser" and p["dealer_id"] != caller["user_id"]:
        raise err_dealer_mismatch()
    return resp.ok(ser.serialize_payment(p))


@bp.route("/dealer-payments", methods=["GET"])
def list_payments():
    caller = mw.authenticate()
    mw.authorize(caller, READ_ROLES)
    limit, offset = mw.pagination_params()
    dealer_id = mw.opt_query_string("dealer_id")
    status = mw.opt_query_enum("status", PAYMENT_STATES)
    if caller["role"] == "DealerUser":
        if dealer_id is not None and dealer_id != caller["user_id"]:
            raise err_dealer_mismatch()
        dealer_id = caller["user_id"]
    items = list(db.dealer_payments.values())
    if dealer_id is not None:
        items = [p for p in items if p["dealer_id"] == dealer_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: p["_seq"])
    total = len(items)
    page = items[offset : offset + limit]
    return resp.list_ok([ser.serialize_payment(p) for p in page], limit, offset, total)


@bp.route("/dealer-payments/<pid>/return", methods=["POST"])
def return_payment(pid):
    caller = mw.authenticate()
    mw.authorize(caller, WRITE_ROLES)
    p = db.dealer_payments.get(pid)
    if p is None:
        raise err_not_found()
    if p["status"] != "POSTED":
        raise err_payment_already_returned()

    # reverse applications in reverse application order
    for app in reversed(p["applications"]):
        o = db.delivery_orders.get(app["order_id"])
        if o is None:
            continue
        o["open_balance_cents"] = (o["open_balance_cents"] or 0) + app["amount_cents"]
        if o["invoice_status"] == "PAID" and o["open_balance_cents"] > 0:
            o["invoice_status"] = "OPEN"
        svc.touch(o)

    p["status"] = "RETURNED"
    svc.touch(p)

    dealer = db.dealers[p["dealer_id"]]
    dealer["fee_balance_cents"] += svc.NSF_FEE_CENTS
    svc.touch(dealer)

    return resp.ok(ser.serialize_payment(p))
