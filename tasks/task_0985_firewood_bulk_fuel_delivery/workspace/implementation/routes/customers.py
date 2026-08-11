"""Customer endpoints (PRD §3.1)."""

from flask import Blueprint

import errors
from db import db, new_id
from middleware import require_roles
from response import success_list, success_object
from services.domain import (
    credit_wallet,
    debit_wallet,
    serialize_customer,
)
from util import (
    get_json_body,
    now_iso,
    paginate,
    parse_pagination,
    require_str,
    touch,
)

bp = Blueprint("customers", __name__)


@bp.post("/api/v1/customers")
def create_customer():
    require_roles("CustomerService", "OperationsManager")
    body = get_json_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    phone = require_str(body, "phone")
    street_address = require_str(body, "street_address")
    postal_code = require_str(body, "postal_code")
    ts = now_iso()
    cid = new_id()
    customer = {
        "id": cid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "street_address": street_address,
        "postal_code": postal_code,
        "credit_balance_cents": 0,
        "outstanding_refund_cents": 0,
        "lifetime_cord_equivalent_delivered": 0,
        "loyalty_tier": "STANDARD",
        "account_status": "ACTIVE",
        "suspended_reason": None,
    }
    db.customers[cid] = customer
    return success_object(serialize_customer(customer), status=201)


def _get_customer_or_404(cid):
    c = db.customers.get(cid)
    if not c:
        raise errors.not_found(f"Customer {cid} not found")
    return c


@bp.get("/api/v1/customers/<cid>")
def get_customer(cid):
    auth = require_roles("CustomerService", "OperationsManager", "Customer")
    customer = _get_customer_or_404(cid)
    if auth.is_customer() and auth.user_id != cid:
        raise errors.unauthorized("Customers may only read their own record")
    return success_object(serialize_customer(customer))


@bp.get("/api/v1/customers")
def list_customers():
    require_roles("CustomerService", "OperationsManager")
    limit, offset = parse_pagination()
    items = list(db.customers.values())
    q = {}
    from flask import request
    for f in ("email", "postal_code", "account_status", "loyalty_tier"):
        v = request.args.get(f)
        if v is not None:
            q[f] = v
    def match(c):
        for k, v in q.items():
            if str(c.get(k)) != v:
                return False
        return True
    items = [c for c in items if match(c)]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_customer(c) for c in page], total, limit, offset)


@bp.post("/api/v1/customers/<cid>/suspend")
def suspend_customer(cid):
    require_roles("OperationsManager")
    customer = _get_customer_or_404(cid)
    body = get_json_body()
    reason = require_str(body, "reason")
    # State check
    if customer["account_status"] != "ACTIVE":
        raise errors.invalid_state("Customer is not ACTIVE")
    # Safety: no order OUT_FOR_DELIVERY
    for o in db.orders.values():
        if o["customer_id"] == cid and o["fulfillment_status"] == "OUT_FOR_DELIVERY":
            raise errors.invalid_state("Cannot suspend while an order is OUT_FOR_DELIVERY")
    # Side effects
    customer["account_status"] = "SUSPENDED"
    customer["suspended_reason"] = reason
    ts = now_iso()
    for s in db.subscriptions.values():
        if s["customer_id"] == cid and s["status"] == "PENDING":
            s["status"] = "CANCELLED"
            s["closed_at"] = ts
            s["updated_at"] = ts
            s["version"] += 1
    touch(customer)
    return success_object(serialize_customer(customer))


@bp.post("/api/v1/customers/<cid>/reinstate")
def reinstate_customer(cid):
    require_roles("OperationsManager")
    customer = _get_customer_or_404(cid)
    if customer["account_status"] != "SUSPENDED":
        raise errors.invalid_state("Customer is not SUSPENDED")
    if customer.get("outstanding_refund_cents", 0) != 0:
        raise errors.outstanding_refund("Outstanding refunds must be settled first")
    customer["account_status"] = "ACTIVE"
    customer["suspended_reason"] = None
    touch(customer)
    return success_object(serialize_customer(customer))


@bp.post("/api/v1/customers/<cid>/close")
def close_customer(cid):
    require_roles("OperationsManager")
    customer = _get_customer_or_404(cid)
    status = customer["account_status"]
    if status not in ("ACTIVE", "SUSPENDED"):
        raise errors.invalid_state("Customer account cannot be closed from current state")
    # No open orders
    blocking_order_states = {"PENDING_PAYMENT", "CONFIRMED", "SCHEDULED", "OUT_FOR_DELIVERY"}
    for o in db.orders.values():
        if o["customer_id"] == cid and o["fulfillment_status"] in blocking_order_states:
            raise errors.invalid_state("Customer has open orders")
    if status == "ACTIVE":
        for s in db.subscriptions.values():
            if s["customer_id"] == cid and s["status"] in ("PENDING", "ACTIVE"):
                raise errors.invalid_state("Customer has open subscriptions")
    if customer.get("outstanding_refund_cents", 0) != 0:
        raise errors.outstanding_refund("Outstanding refunds must be settled first")
    # Transfer credit to outstanding refund (amount owed to customer)
    credit = customer.get("credit_balance_cents", 0)
    if credit:
        customer["credit_balance_cents"] = 0
        customer["outstanding_refund_cents"] = customer.get("outstanding_refund_cents", 0) + credit
    customer["account_status"] = "CLOSED"
    touch(customer)
    return success_object(serialize_customer(customer))


@bp.post("/api/v1/customers/<cid>/wallet-adjustments")
def wallet_adjustment(cid):
    require_roles("OperationsManager")
    customer = _get_customer_or_404(cid)
    body = get_json_body()
    amount = body.get("amount_cents")
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise errors.validation("amount_cents must be an integer")
    require_str(body, "reason")
    if amount >= 0:
        credit_wallet(customer, amount)
    else:
        debit_wallet(customer, -amount)
    touch(customer)
    return success_object(serialize_customer(customer), status=201)
