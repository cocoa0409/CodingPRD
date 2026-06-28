from flask import Blueprint, request

from db import db, touch
from errors import ApiError
from middleware import get_identity, require_role
from response import success, list_response
from services import serialize
from services.common import (
    get_invoice, get_pagination, paginate, sorted_by_creation,
)
from services.domain import recompute_outstanding_balance

bp = Blueprint("invoices", __name__)


@bp.get("/invoices")
def list_invoices():
    user_id, role = get_identity()
    require_role(role, {"Dispatcher", "BillingAdmin", "Customer"})
    visit_id = request.args.get("visit_id")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    limit, offset = get_pagination()
    items = []
    for inv in db.invoices.values():
        if visit_id is not None and inv["visit_id"] != visit_id:
            continue
        if customer_id is not None and inv["customer_id"] != customer_id:
            continue
        if status is not None and inv["status"] != status:
            continue
        if role == "Customer" and inv["customer_id"] != user_id:
            continue
        items.append(inv)
    items = sorted_by_creation(items)
    page, total = paginate(items, limit, offset)
    return list_response([serialize.invoice_view(i) for i in page], limit, offset, total)


@bp.get("/invoices/<iid>")
def get_one_invoice(iid):
    user_id, role = get_identity()
    require_role(role, {"Dispatcher", "BillingAdmin", "Customer"})
    inv = get_invoice(iid)
    if role == "Customer" and inv["customer_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning customer")
    return success(serialize.invoice_view(inv), 200)


@bp.post("/invoices/<iid>/pay")
def pay_invoice(iid):
    _, role = get_identity()
    require_role(role, {"BillingAdmin"})
    inv = get_invoice(iid)
    if inv["status"] not in ("ISSUED", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE", "Only an ISSUED/DISPUTED invoice can be paid")
    inv["status"] = "PAID"
    touch(inv)
    customer = db.customers.get(inv["customer_id"])
    if customer is not None:
        recompute_outstanding_balance(customer)
    return success(serialize.invoice_view(inv), 200)


@bp.post("/invoices/<iid>/dispute")
def dispute_invoice(iid):
    user_id, role = get_identity()
    require_role(role, {"Customer"})
    inv = get_invoice(iid)
    # Ownership (priority 4) before state (priority 6).
    if inv["customer_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Not the owning customer")
    if inv["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE", "Only an ISSUED invoice can be disputed")
    inv["status"] = "DISPUTED"
    touch(inv)
    customer = db.customers.get(inv["customer_id"])
    if customer is not None:
        # DISPUTED stays in the balance sum; recompute is a no-op on total
        # but is still a mutation of the customer record (§2.9).
        recompute_outstanding_balance(customer)
    return success(serialize.invoice_view(inv), 200)


@bp.post("/invoices/<iid>/void")
def void_invoice(iid):
    _, role = get_identity()
    require_role(role, {"BillingAdmin"})
    inv = get_invoice(iid)
    if inv["status"] not in ("ISSUED", "DISPUTED"):
        raise ApiError("ERR_INVALID_STATE", "Only an ISSUED/DISPUTED invoice can be voided")
    inv["status"] = "VOIDED"
    touch(inv)
    # Cascade: linked Visit.billing_status -> VOIDED.
    visit = db.visits.get(inv["visit_id"])
    if visit is not None:
        visit["billing_status"] = "VOIDED"
        touch(visit)
    customer = db.customers.get(inv["customer_id"])
    if customer is not None:
        recompute_outstanding_balance(customer)
    return success(serialize.invoice_view(inv), 200)
