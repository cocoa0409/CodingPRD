"""CreditMemo endpoints: get/list, apply (owner), void (TerritoryManager)."""

from flask import Blueprint, request

from db import DB
from middleware import require_role, require_any
from util import (
    get_json_body, check_unknown_fields, require_fields, paginate, err,
    touch, apply_changes,
)
from response import success_object, success_list
from errors import (
    ERR_CREDIT_MEMO_NOT_FOUND, ERR_INVOICE_NOT_FOUND, ERR_OWNERSHIP_MISMATCH,
    ERR_CREDIT_MEMO_NOT_APPLICABLE, ERR_CREDIT_MEMO_NOT_VOIDABLE,
    ERR_INVOICE_NOT_OPEN,
)
from serializers import serialize_credit_memo
from services import apply_memo_to_invoice, recompute_invoice_status_and_order, refresh_store_open_ar

bp = Blueprint("credit_memos", __name__)


def get_memo_or_404(memo_id):
    m = DB.credit_memos.get(memo_id)
    if m is None:
        raise err(ERR_CREDIT_MEMO_NOT_FOUND, "CreditMemo id not found")
    return m


def owner_check_memo(user_id, memo):
    store = DB.stores.get(memo["store_id"])
    route = DB.routes.get(store["route_id"]) if store else None
    if route is None or route["distributor_id"] != user_id:
        raise err(ERR_OWNERSHIP_MISMATCH,
                  "Caller does not own the memo's store route chain")


@bp.get("/dairy/credit-memos/<memoId>")
def get_memo(memoId):
    require_any()
    return success_object(serialize_credit_memo(get_memo_or_404(memoId)))


@bp.get("/dairy/credit-memos")
def list_memos():
    require_any()
    items = list(DB.credit_memos.values())
    for param, field in (("return_id", "return_id"), ("store_id", "store_id"),
                         ("invoice_id", "invoice_id"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [m for m in items if m[field] == v]
    items.sort(key=lambda m: m["_seq"])
    page, limit, offset, total = paginate(items)
    return success_list([serialize_credit_memo(m) for m in page], limit, offset, total)


@bp.post("/dairy/credit-memos/<memoId>/apply")
def apply_memo(memoId):
    user_id, _role = require_role("DistributorOwner")
    m = get_memo_or_404(memoId)
    owner_check_memo(user_id, m)
    body = get_json_body()
    check_unknown_fields(body, {"invoice_id"})
    require_fields(body, ["invoice_id"])
    invoice = DB.invoices.get(body["invoice_id"])
    if invoice is None:
        raise err(ERR_INVOICE_NOT_FOUND, "Invoice id not found")
    if m["status"] not in ("ISSUED", "PARTIALLY_APPLIED"):
        raise err(ERR_CREDIT_MEMO_NOT_APPLICABLE,
                  "Apply requires a memo in ISSUED or PARTIALLY_APPLIED")
    if invoice["store_id"] != m["store_id"] or invoice["status"] != "OPEN":
        raise err(ERR_INVOICE_NOT_OPEN,
                  "Target invoice must belong to the memo's store and be OPEN")
    apply_memo_to_invoice(m, invoice)
    return success_object(serialize_credit_memo(m))


@bp.post("/dairy/credit-memos/<memoId>/void")
def void_memo(memoId):
    require_role("TerritoryManager")
    m = get_memo_or_404(memoId)
    if m["status"] not in ("ISSUED", "PARTIALLY_APPLIED"):
        raise err(ERR_CREDIT_MEMO_NOT_VOIDABLE,
                  "Void requires a memo in ISSUED or PARTIALLY_APPLIED")
    # Compensation: reverse every application this memo ever made.
    affected_invoices = {}
    for invoice_id, amount in m["_applications"]:
        affected_invoices[invoice_id] = affected_invoices.get(invoice_id, 0) + amount
    for invoice_id, amount in affected_invoices.items():
        inv = DB.invoices.get(invoice_id)
        if inv is None:
            continue
        inv["credits_applied_cents"] -= amount
        if inv["status"] == "SETTLED":
            inv["status"] = "OPEN"  # a SETTLED invoice reopens
        recompute_invoice_status_and_order(inv)
    m["status"] = "VOID"
    m["applied_cents"] = 0
    m["remaining_cents"] = m["amount_cents"]
    m["invoice_id"] = None
    m["_applications"] = []
    touch(m)
    refresh_store_open_ar(m["store_id"])
    return success_object(serialize_credit_memo(m))
