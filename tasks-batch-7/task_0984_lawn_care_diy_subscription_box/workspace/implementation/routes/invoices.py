from flask import Blueprint, request

from db import store, touch
from errors import raise_err, ERR_INVOICE_NOT_FOUND, ERR_INVOICE_NOT_PAYABLE
from middleware import get_body, authenticate, check_ownership, paginate, sort_items
from response import ok, ok_list
from serializers import ser_invoice
from services import maybe_qualify_referral
from util import req_enum

bp = Blueprint("invoices", __name__)

READ_ROLES = ["Customer", "PlatformAdmin"]


def _get_invoice_or_404(iid):
    rec = store.invoices.get(iid)
    if rec is None:
        raise_err(ERR_INVOICE_NOT_FOUND, "Invoice not found")
    return rec


def _owner_of_invoice(inv):
    sub = store.subscriptions.get(inv.subscription_id)
    return sub.customer_id if sub else None


@bp.route("/api/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    uid, role = authenticate(READ_ROLES)
    rec = _get_invoice_or_404(iid)
    check_ownership(uid, role, _owner_of_invoice(rec))
    return ok(ser_invoice(rec))


@bp.route("/api/invoices", methods=["GET"])
def list_invoices():
    uid, role = authenticate(READ_ROLES)
    items = list(store.invoices.values())
    if role == "Customer":
        own_subs = {s.id for s in store.subscriptions.values() if s.customer_id == uid}
        items = [i for i in items if i.subscription_id in own_subs]
    for param in ("subscription_id", "shipment_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [i for i in items if getattr(i, param) == v]
    items = sort_items(items)
    page, total, limit, offset = paginate(items)
    return ok_list([ser_invoice(i) for i in page], total, limit, offset)


@bp.route("/api/invoices/<iid>/record-payment", methods=["POST"])
def record_payment(iid):
    body = get_body()
    outcome = req_enum(body, "outcome", {"SUCCEEDED", "FAILED"})
    authenticate(["PlatformAdmin"])
    inv = _get_invoice_or_404(iid)
    if inv.status not in ("ISSUED", "FAILED"):
        raise_err(ERR_INVOICE_NOT_PAYABLE, "record-payment requires invoice ISSUED or FAILED")

    box = store.shipments.get(inv.shipment_id)
    sub = store.subscriptions.get(inv.subscription_id)
    if outcome == "SUCCEEDED":
        inv.status = "PAID"
        if box is not None and box.billing_status != "PAID":
            box.billing_status = "PAID"
            touch(box)
        if sub is not None and sub.status == "PAST_DUE":
            sub.status = "ACTIVE"
            touch(sub)
        touch(inv)
        maybe_qualify_referral(inv)
    else:  # FAILED
        already_failed = inv.status == "FAILED"
        inv.status = "FAILED"
        if not already_failed:
            if box is not None:
                box.billing_status = "FAILED"
                touch(box)
            if sub is not None and sub.status == "ACTIVE":
                sub.status = "PAST_DUE"
                touch(sub)
        # FAILED -> FAILED: box stays FAILED, subscription stays PAST_DUE,
        # only the invoice version increments (scaffold Invoice machine)
        touch(inv)
    return ok(ser_invoice(inv))
