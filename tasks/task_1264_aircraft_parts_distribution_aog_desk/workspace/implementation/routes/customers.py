"""Customer endpoints: onboarding, credit adjustments, suspend/reactivate,
ledger listing."""

from flask import Blueprint, request

from auth import require_roles, ALL_BUSINESS, LEDGER_READERS
from db import store
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_CUSTOMER_NOT_FOUND, ERR_ORDER_NOT_FOUND,
                    ERR_STALE_CUSTOMER_VERSION, ERR_CREDIT_LIMIT_EXCEEDED)
from helpers import (new_record, touch, get_or_404, post_ledger, ser_customer,
                     ser_ledger, sort_asc, sort_desc)
from util import (success, get_body, page_params, paged, req_present, as_str,
                  as_int, bad)

bp = Blueprint("customers", __name__)


@bp.post("/aog/customers")
def create_customer():
    require_roles("FinanceController")
    body = get_body()
    name = as_str(req_present(body, "name"), "name")
    country = as_str(req_present(body, "country_code"), "country_code")
    limit = as_int(req_present(body, "credit_limit_cents"), "credit_limit_cents")
    if limit < 0:
        bad("credit_limit_cents must be >= 0")
    rec = new_record("customers", {
        "name": name,
        "country_code": country,
        "credit_limit_cents": limit,
        "outstanding_balance_cents": 0,
        "priority_tier": "STANDARD",
        "core_returns_settled_180d": 0,
        "core_returns_on_time_180d": 0,
        "warranty_fraud_flags": 0,
        "status": "ACTIVE",
    })
    return success(ser_customer(rec), 201)


@bp.get("/aog/customers")
def list_customers():
    uid, role = require_roles(*ALL_BUSINESS)
    limit, offset = page_params()
    recs = list(store["customers"].values())
    if role == "CustomerContact":
        recs = [c for c in recs if c["id"] == uid]
    q = request.args
    if q.get("status") is not None:
        recs = [c for c in recs if c["status"] == q.get("status")]
    if q.get("priority_tier") is not None:
        recs = [c for c in recs if c["priority_tier"] == q.get("priority_tier")]
    return paged([ser_customer(c) for c in sort_asc(recs)], limit, offset)


@bp.get("/aog/customers/<cid>")
def get_customer(cid):
    require_roles(*ALL_BUSINESS)
    rec = get_or_404("customers", cid, ERR_CUSTOMER_NOT_FOUND, "Customer")
    return success(ser_customer(rec))


@bp.post("/aog/customers/<cid>/credit-adjustments")
def credit_adjustment(cid):
    require_roles("FinanceController")
    customer = get_or_404("customers", cid, ERR_CUSTOMER_NOT_FOUND, "Customer")
    body = get_body()
    entry_type = req_present(body, "entry_type")
    if entry_type not in ("PAYMENT_CREDIT", "MANUAL_DEBIT", "MANUAL_CREDIT"):
        bad("entry_type must be PAYMENT_CREDIT, MANUAL_DEBIT or MANUAL_CREDIT")
    amount = as_int(req_present(body, "amount_cents"), "amount_cents")
    if amount <= 0:
        bad("amount_cents must be positive")
    if "expected_customer_version" not in body or \
            body["expected_customer_version"] is None:
        bad("expected_customer_version is required")
    expected = as_int(body["expected_customer_version"],
                      "expected_customer_version")
    memo = body.get("memo")
    if memo is not None and not isinstance(memo, str):
        bad("memo must be a string")
    order_id = body.get("order_id")
    order = None
    if entry_type == "PAYMENT_CREDIT" and not order_id:
        bad("order_id is required for PAYMENT_CREDIT")
    if order_id is not None:
        order = get_or_404("orders", order_id, ERR_ORDER_NOT_FOUND,
                           "SalesOrder")
    # OCC gate
    if expected != customer["version"]:
        raise ApiError(ERR_STALE_CUSTOMER_VERSION, 412,
                       "expected_customer_version does not match current "
                       "customer version")
    if order is not None:
        ref_type, ref_id = "SALES_ORDER", order["id"]
    else:
        ref_type, ref_id = "CUSTOMER", customer["id"]
    entry = post_ledger(customer["id"], entry_type, amount, ref_type, ref_id,
                        memo)
    # payment flip: cumulative PAYMENT_CREDIT on an invoiced order
    if order is not None and entry_type == "PAYMENT_CREDIT" and \
            order["payment_status"] == "INVOICED":
        paid = sum(e["amount_cents"] for e in store["ledger"].values()
                   if e["entry_type"] == "PAYMENT_CREDIT"
                   and e["reference_type"] == "SALES_ORDER"
                   and e["reference_id"] == order["id"])
        if paid >= order["invoiced_cents"]:
            order["payment_status"] = "PAID"
            touch(order)
    return success(ser_ledger(entry), 201)


@bp.post("/aog/customers/<cid>/suspend")
def suspend_customer(cid):
    require_roles("FinanceController")
    customer = get_or_404("customers", cid, ERR_CUSTOMER_NOT_FOUND, "Customer")
    if customer["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an ACTIVE customer can be suspended")
    customer["status"] = "SUSPENDED"
    touch(customer)
    return success(ser_customer(customer))


@bp.post("/aog/customers/<cid>/reactivate")
def reactivate_customer(cid):
    require_roles("FinanceController")
    customer = get_or_404("customers", cid, ERR_CUSTOMER_NOT_FOUND, "Customer")
    if customer["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only a SUSPENDED customer can be reactivated")
    if customer["outstanding_balance_cents"] > customer["credit_limit_cents"]:
        raise ApiError(ERR_CREDIT_LIMIT_EXCEEDED, 402,
                       "Outstanding balance exceeds credit limit")
    customer["status"] = "ACTIVE"
    touch(customer)
    return success(ser_customer(customer))


@bp.get("/aog/customers/<cid>/ledger-entries")
def list_ledger(cid):
    require_roles(*LEDGER_READERS)
    get_or_404("customers", cid, ERR_CUSTOMER_NOT_FOUND, "Customer")
    limit, offset = page_params()
    recs = [e for e in store["ledger"].values() if e["customer_id"] == cid]
    q = request.args
    if q.get("entry_type") is not None:
        recs = [e for e in recs if e["entry_type"] == q.get("entry_type")]
    recs = sort_desc(recs)  # explicit exception: newest first
    return paged([ser_ledger(e) for e in recs], limit, offset)
