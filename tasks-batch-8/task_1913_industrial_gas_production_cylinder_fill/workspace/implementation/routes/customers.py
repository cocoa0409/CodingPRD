"""CustomerAccount endpoints (PRD §3.5)."""
from flask import Blueprint

from constants import BILLING_VARIANTS
from db import store
from errors import ERR_STALE_VERSION, ApiError, bad_request, not_found
from middleware import ANY_ROLE, get_body, locked, req_enum, req_int, req_str, require_roles
from response import success
from routes.listing import list_response
from services.ops import base_record, credit_evaluate, customer_out
from util import is_int, touch

bp = Blueprint("customers", __name__)


@bp.post("/api/customers")
@locked
def create_customer():
    require_roles("BillingClerk")
    body = get_body()
    name = req_str(body, "account_name")
    variant = req_enum(body, "billing_variant", BILLING_VARIANTS)
    free_days = req_int(body, "free_days")
    credit_limit = req_int(body, "credit_limit_cents")
    if free_days < 0:
        bad_request("free_days must be >= 0")
    if credit_limit <= 0:
        bad_request("credit_limit_cents must be > 0")
    c = base_record()
    c.update(
        {
            "account_name": name,
            "billing_variant": variant,
            "free_days": free_days,
            "credit_limit_cents": credit_limit,
            "outstanding_balance_cents": 0,
            "recall_flag": False,
            "status": "ACTIVE",
        }
    )
    store.customers[c["id"]] = c
    return success(customer_out(c), status=201)


@bp.get("/api/customers")
@locked
def list_customers():
    require_roles(*ANY_ROLE)
    return list_response(
        store.customers.values(),
        customer_out,
        [("status", "status"), ("billing_variant", "billing_variant")],
    )


@bp.get("/api/customers/<customerId>")
@locked
def get_customer(customerId):
    require_roles(*ANY_ROLE)
    c = store.customers.get(customerId)
    if c is None:
        not_found("customer not found")
    return success(customer_out(c))


@bp.patch("/api/customers/<customerId>")
@locked
def patch_customer(customerId):
    require_roles("BillingClerk")
    body = get_body()
    expected = body.get("expected_customer_version")
    if expected is None or not is_int(expected):
        bad_request("expected_customer_version is required and must be an integer")
    credit_limit = body.get("credit_limit_cents")
    if credit_limit is not None and (not is_int(credit_limit) or credit_limit <= 0):
        bad_request("credit_limit_cents must be an integer > 0")
    free_days = body.get("free_days")
    if free_days is not None and (not is_int(free_days) or free_days < 0):
        bad_request("free_days must be an integer >= 0")
    variant = body.get("billing_variant")
    if variant is not None and (not isinstance(variant, str) or variant not in BILLING_VARIANTS):
        from errors import bad_enum

        bad_enum("billing_variant must be CALENDAR_DAY or GRACE_PERIOD")
    c = store.customers.get(customerId)
    if c is None:
        not_found("customer not found")
    if expected != c["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "customer version is stale")
    if credit_limit is not None:
        c["credit_limit_cents"] = credit_limit
    if free_days is not None:
        c["free_days"] = free_days
    if variant is not None:
        c["billing_variant"] = variant
    touch(c)
    return success(customer_out(c))


@bp.post("/api/customers/<customerId>/payments")
@locked
def post_payment(customerId):
    require_roles("BillingClerk")
    body = get_body()
    amount = req_int(body, "amount_cents")
    if amount <= 0:
        bad_request("amount_cents must be > 0")
    c = store.customers.get(customerId)
    if c is None:
        not_found("customer not found")
    if amount > c["outstanding_balance_cents"]:
        bad_request("payment exceeds the outstanding balance")
    c["outstanding_balance_cents"] -= amount
    touched = {c["id"]}
    touch(c)
    credit_evaluate(c, touched)
    return success(customer_out(c))
