"""Customers (PRD §3.1)."""

from flask import Blueprint, request

from db import public, sort_by_creation, stamp_new, store, touch
from middleware import forbid_unless_owner, get_ctx, require_roles
from response import success
from routes.helpers import get_customer
from validation import get_body, opt_enum, opt_int, paginate, req_int, req_str

bp = Blueprint("customers", __name__)

PRIORITY_CLASSES = {"STANDARD", "PRIORITY_CONTRACT"}
ACCOUNT_STATUSES = {"ACTIVE", "SUSPENDED"}


@bp.post("/customers")
def create_customer():
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    body = get_body()
    name = req_str(body, "name")
    credit_limit = req_int(body, "credit_limit_cents", minimum=0)
    prepaid = opt_int(body, "prepaid_balance_cents", default=0, minimum=0)
    priority = opt_enum(body, "priority_class", PRIORITY_CLASSES, default="STANDARD")
    rec = stamp_new(
        {
            "name": name,
            "credit_limit_cents": credit_limit,
            "prepaid_balance_cents": prepaid,
            "priority_class": priority,
            "account_status": "ACTIVE",
        }
    )
    store.customers[rec["id"]] = rec
    return success(public(rec), code=201)


@bp.get("/customers")
def list_customers():
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    records = list(store.customers.values())
    status_filter = request.args.get("account_status")
    if status_filter is not None:
        records = [c for c in records if c["account_status"] == status_filter]
    records = sort_by_creation(records)
    page, meta = paginate(records, request.args)
    return success([public(r) for r in page], response_type="array", pagination=meta)


@bp.get("/customers/<cid>")
def get_one_customer(cid):
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager", "Grower"})
    rec = get_customer(cid)
    forbid_unless_owner(ctx, rec["id"])
    return success(public(rec))


@bp.patch("/customers/<cid>")
def update_customer(cid):
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager"})
    rec = get_customer(cid)
    body = get_body()
    if "credit_limit_cents" in body and body["credit_limit_cents"] is not None:
        rec["credit_limit_cents"] = req_int(body, "credit_limit_cents", minimum=0)
    if "account_status" in body and body["account_status"] is not None:
        rec["account_status"] = opt_enum(body, "account_status", ACCOUNT_STATUSES)
    if "priority_class" in body and body["priority_class"] is not None:
        rec["priority_class"] = opt_enum(body, "priority_class", PRIORITY_CLASSES)
    touch(rec)
    return success(public(rec))


@bp.get("/customers/<cid>/statement")
def customer_statement(cid):
    ctx = get_ctx()
    require_roles(ctx, {"ElevatorManager", "Grower"})
    rec = get_customer(cid)
    forbid_unless_owner(ctx, rec["id"])
    issued = [
        inv
        for inv in store.invoices.values()
        if inv["customer_id"] == rec["id"] and inv["status"] == "ISSUED"
    ]
    data = {
        "customer_id": rec["id"],
        "outstanding_due_cents": sum(inv["amount_due_cents"] for inv in issued),
        "prepaid_balance_cents": rec["prepaid_balance_cents"],
        "issued_invoice_count": len(issued),
    }
    return success(data)
