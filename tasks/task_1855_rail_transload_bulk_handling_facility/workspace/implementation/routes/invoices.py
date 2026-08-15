"""Invoice endpoints: create (DRAFT), get, list, issue (sweeps matching
ACCRUED charges per invoice_total), pay, dispute."""

from flask import Blueprint, request

from db import STORE, new_entity, touch, public, iso
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_INVOICE_EMPTY,
)
from middleware import auth_context, require_role, require_ownership, ALL_ROLES
from response import ok, paginated
from util import parse_datetime
from validate import body, req_str, req_datetime

bp = Blueprint("invoices", __name__)


def _get_invoice_or_404(invoice_id):
    inv = STORE.invoices.get(invoice_id)
    if inv is None:
        raise_err(ERR_NOT_FOUND, "invoice id does not exist")
    return inv


@bp.route("/transload/invoices", methods=["POST"])
def create_invoice():
    _, role = auth_context()
    require_role(role, ["BillingClerk", "FacilityAdmin"])
    data = body()
    # Priority 3: body FK ids resolve.
    raw_customer = data.get("customer_id")
    if isinstance(raw_customer, str) and raw_customer not in STORE.customers:
        raise_err(ERR_NOT_FOUND, "customer id does not exist")
    customer_id = req_str(data, "customer_id")
    period_start = req_datetime(data, "period_start")
    period_end = req_datetime(data, "period_end")
    if period_end < period_start:
        raise_err(ERR_INVALID_REQUEST, "period_end must be at least period_start")
    inv = new_entity(STORE.invoices, {
        "customer_id": customer_id,
        "period_start": iso(period_start),
        "period_end": iso(period_end),
        "charge_count": 0,
        "total_cents": 0,
        "status": "DRAFT",
    })
    return ok(public(inv), status=201)


@bp.route("/transload/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    user_id, role = auth_context()
    require_role(role, ALL_ROLES)
    inv = _get_invoice_or_404(iid)
    require_ownership(user_id, role, inv["customer_id"])
    return ok(public(inv))


@bp.route("/transload/invoices", methods=["GET"])
def list_invoices():
    user_id, role = auth_context()
    require_role(role, ALL_ROLES)
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    if role == "CustomerRep":
        if customer_id is not None and customer_id != user_id:
            require_ownership(user_id, role, customer_id)
        customer_id = user_id
    items = sorted(STORE.invoices.values(), key=lambda i: (i["created_at"], i["_seq"]))
    if customer_id is not None:
        items = [i for i in items if i["customer_id"] == customer_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    page, meta = paginated(items)
    return ok([public(i) for i in page], pagination=meta)


@bp.route("/transload/invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    _, role = auth_context()
    require_role(role, ["BillingClerk", "FacilityAdmin"])
    inv = _get_invoice_or_404(iid)
    if inv["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "invoice is not DRAFT")
    period_start = parse_datetime(inv["period_start"])
    period_end = parse_datetime(inv["period_end"])
    eligible = [
        c for c in sorted(STORE.charges.values(), key=lambda c: (c["created_at"], c["_seq"]))
        if c["customer_id"] == inv["customer_id"]
        and c["status"] == "ACCRUED"
        and period_start <= parse_datetime(c["created_at"]) <= period_end
    ]
    if not eligible:
        raise_err(ERR_INVOICE_EMPTY, "no matching ACCRUED charges in the period")
    for charge in eligible:
        charge["status"] = "INVOICED"
        charge["invoice_id"] = inv["id"]
        touch(charge)
    inv["charge_count"] = len(eligible)
    inv["total_cents"] = sum(c["amount_cents"] for c in eligible)
    inv["status"] = "ISSUED"
    touch(inv)
    return ok(public(inv))


@bp.route("/transload/invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    user_id, role = auth_context()
    require_role(role, ["CustomerRep", "BillingClerk"])
    inv = _get_invoice_or_404(iid)
    if inv["status"] != "ISSUED":
        raise_err(ERR_INVALID_STATE, "invoice is not ISSUED")
    require_ownership(user_id, role, inv["customer_id"])
    inv["status"] = "PAID"
    touch(inv)
    return ok(public(inv))


@bp.route("/transload/invoices/<iid>/dispute", methods=["POST"])
def dispute_invoice(iid):
    user_id, role = auth_context()
    require_role(role, ["CustomerRep"])
    inv = _get_invoice_or_404(iid)
    if inv["status"] != "ISSUED":
        raise_err(ERR_INVALID_STATE, "invoice is not ISSUED")
    require_ownership(user_id, role, inv["customer_id"])
    inv["status"] = "DISPUTED"
    touch(inv)
    return ok(public(inv))
