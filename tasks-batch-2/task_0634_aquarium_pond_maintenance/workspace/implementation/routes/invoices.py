"""Invoice + payment endpoints (PRD §3.10)."""

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import get_auth, require_roles
from response import object_response, array_response
from serializers import invoice_view
import common as C

bp = Blueprint("invoices", __name__)


@bp.get("/aquatics/invoices/<iid>")
def get_invoice(iid):
    _, role = get_auth()
    require_roles(role, {"AccountManager", "CustomerOwner"})
    rec = store.invoices.get(iid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Invoice not found.")
    return object_response(invoice_view(rec))


@bp.get("/aquatics/contracts/<cid>/invoices")
def list_contract_invoices(cid):
    _, role = get_auth()
    require_roles(role, {"AccountManager", "CustomerOwner"})
    if cid not in store.contracts:
        raise ApiError("ERR_NOT_FOUND", "Contract not found.")
    limit, offset = C.parse_pagination(request.args)
    status = request.args.get("status")
    source_kind = request.args.get("source_kind")
    recs = [i for i in store.invoices.values() if i["contract_id"] == cid]
    if status is not None:
        recs = [i for i in recs if i["status"] == status]
    if source_kind is not None:
        recs = [i for i in recs if i["source_kind"] == source_kind]
    page, total = C.paginate(recs, limit, offset)
    return array_response([invoice_view(r) for r in page], limit, offset, total)


@bp.post("/aquatics/invoices/<iid>/payments")
def apply_payment(iid):
    _, role = get_auth()
    require_roles(role, {"AccountManager"})
    rec = store.invoices.get(iid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Invoice not found.")
    # payable only when ISSUED or OVERDUE (priority 5 / state)
    if rec["status"] not in ("ISSUED", "OVERDUE"):
        raise ApiError("ERR_INVOICE_NOT_PAYABLE", "Invoice is not payable.")
    data = C.require_body(request.get_json(silent=True))
    amount = C.req_int(data, "amount_cents")
    # payment guard (priority 14): > 0 and must not overpay
    if amount <= 0:
        raise ApiError("ERR_OVERPAYMENT", "Payment must be greater than zero.")
    if rec["amount_paid_cents"] + amount > rec["total_cents"]:
        raise ApiError("ERR_OVERPAYMENT", "Payment would exceed the invoice total.")
    rec["amount_paid_cents"] += amount
    if rec["amount_paid_cents"] == rec["total_cents"]:
        rec["status"] = "PAID"
    C.touch(rec)
    contract = store.contracts.get(rec["contract_id"])
    if contract is not None:
        C.recompute_account_balance(contract)
    return object_response(invoice_view(rec))


@bp.post("/aquatics/invoices/<iid>/flag-overdue")
def flag_overdue(iid):
    _, role = get_auth()
    require_roles(role, {"AccountManager"})
    rec = store.invoices.get(iid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Invoice not found.")
    if rec["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Only an ISSUED invoice may be flagged overdue.")
    # past its due_on relative to the logical clock
    due = C.parse_iso(rec["due_on"]) if rec["due_on"] else None
    if due is None or store.current_utc <= due:
        raise ApiError("ERR_INVALID_STATE", "Invoice is not past its due date.")
    rec["status"] = "OVERDUE"
    C.touch(rec)
    # no balance change (ISSUED and OVERDUE both count)
    return object_response(invoice_view(rec))
