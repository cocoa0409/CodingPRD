"""Invoices and payments (read + payment application)."""
from flask import Blueprint, request

import errors
from db import store
from middleware import get_identity, require_role
from helpers import (
    get_body, require_fields, as_int, parse_pagination, paginate,
    sort_by_created, new_record, touch,
)
from response import object_response, array_response
from services import lookups, serializers
from services.inventory import invoice_amount_due, recompute_account_balance

bp = Blueprint("invoices", __name__)


@bp.get("/accounts/<aid>/invoices")
def list_account_invoices(aid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff", "WholesaleBuyer"})
    lookups.assert_buyer_owns_account(role, user_id, aid)
    lookups.get_account(aid)
    limit, offset = parse_pagination()
    status = request.args.get("status")
    order_id = request.args.get("order_id")
    items = [i for i in store.invoices.values() if i["account_id"] == aid]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if order_id is not None:
        items = [i for i in items if i["order_id"] == order_id]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.invoice_public(i) for i in page], limit, offset, total)


@bp.get("/invoices")
def list_invoices():
    _, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff"})
    limit, offset = parse_pagination()
    order_id = request.args.get("order_id")
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    items = list(store.invoices.values())
    if order_id is not None:
        items = [i for i in items if i["order_id"] == order_id]
    if account_id is not None:
        items = [i for i in items if i["account_id"] == account_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.invoice_public(i) for i in page], limit, offset, total)


@bp.get("/invoices/<iid>")
def get_invoice(iid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff", "WholesaleBuyer"})
    rec = lookups.get_invoice(iid)
    lookups.assert_buyer_owns_account(role, user_id, rec["account_id"])
    return object_response(serializers.invoice_public(rec))


@bp.post("/invoices/<iid>/payments")
def create_payment(iid):
    _, role = get_identity()
    require_role(role, {"SalesRep"})
    invoice = lookups.get_invoice(iid)
    body = get_body()
    require_fields(body, ["amount_cents"])
    amount = as_int(body["amount_cents"], "amount_cents")
    if amount <= 0:
        raise errors.invalid_request("amount_cents must be greater than zero")
    # state gate (priority 6): invoice payable while ISSUED, OVERDUE, or PARTIALLY_PAID
    if invoice["status"] not in ("ISSUED", "OVERDUE", "PARTIALLY_PAID"):
        raise errors.invalid_state("invoice is not in a payable state")
    # payment sanity (priority 14): 0 < amount <= amount_due
    due = invoice_amount_due(invoice)
    if amount > due:
        raise errors.overpayment("payment exceeds amount due")

    pay = new_record(with_version=False)
    pay.update({
        "invoice_id": invoice["id"],
        "amount_cents": amount,
        "status": "CLEARED",
    })
    store.payments[pay["id"]] = pay

    # recompute invoice paid/amount_due/status
    new_due = invoice_amount_due(invoice)
    if new_due == 0:
        invoice["status"] = "PAID"
    else:
        invoice["status"] = "PARTIALLY_PAID"
    touch(invoice)

    # recompute account balance; possibly release CREDIT_HOLD
    account = store.accounts[invoice["account_id"]]
    recompute_account_balance(account, bump=True)
    _maybe_release_hold(account)

    return object_response(serializers.payment_public(pay), 201)


def _maybe_release_hold(account):
    """If the account was CREDIT_HOLD but is now under limit with no overdue
    invoice, return it to ACTIVE (PRD §3.6)."""
    if account["status"] != "CREDIT_HOLD":
        return
    has_overdue = any(
        i["account_id"] == account["id"] and i["status"] == "OVERDUE"
        for i in store.invoices.values()
    )
    under_limit = account["outstanding_balance_cents"] <= account["credit_limit_cents"]
    if not has_overdue and under_limit:
        account["status"] = "ACTIVE"
        touch(account)


@bp.get("/invoices/<iid>/payments")
def list_payments(iid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff", "WholesaleBuyer"})
    invoice = lookups.get_invoice(iid)
    lookups.assert_buyer_owns_account(role, user_id, invoice["account_id"])
    limit, offset = parse_pagination()
    items = [p for p in store.payments.values() if p["invoice_id"] == iid]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.payment_public(p) for p in page], limit, offset, total)
