"""CustomerAccount endpoints (PRD section 3.4)."""

from flask import Blueprint

import calc
from db import store, new_entity, touch, public
from errors import ApiError, ERR_INVALID_STATE, ERR_CUSTOMER_BALANCE_NOT_ZERO
from middleware import authenticate, authorize
from response import success
from util import body_json, req_field, as_str, as_int, resolve_customer, paginate, query_filter

bp = Blueprint("customers", __name__)

CUSTOMER_READ_ROLES = ["AccountsReceivable", "PlantOperator", "QualityManager", "ComplianceOfficer"]
CHARGE_TERMINAL_STATES = ("RELEASED", "REJECTED", "SCRAPPED")


@bp.route("/customers", methods=["POST"])
def create_customer():
    body = body_json()
    customer_name = as_str(req_field(body, "customer_name"), "customer_name")
    credit_limit = as_int(req_field(body, "credit_limit_cents"), "credit_limit_cents")
    _, role = authenticate()
    authorize(role, ["AccountsReceivable"])
    cust = new_entity()
    cust.update({
        "customer_name": customer_name,
        "credit_limit_cents": credit_limit,
        "outstanding_balance_cents": 0,
        "status": "ACTIVE",
    })
    store.customers[cust["id"]] = cust
    return success(public(cust), status=201)


@bp.route("/customers", methods=["GET"])
def list_customers():
    _, role = authenticate()
    authorize(role, CUSTOMER_READ_ROLES)
    items = list(store.customers.values())
    status = query_filter("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


@bp.route("/customers/<customerId>", methods=["GET"])
def get_customer(customerId):
    _, role = authenticate()
    authorize(role, CUSTOMER_READ_ROLES)
    return success(public(resolve_customer(customerId)))


@bp.route("/customers/<customerId>/record-payment", methods=["POST"])
def record_payment(customerId):
    body = body_json()
    amount = as_int(req_field(body, "amount_cents"), "amount_cents")
    _, role = authenticate()
    authorize(role, ["AccountsReceivable"])
    cust = resolve_customer(customerId)
    if cust["status"] == "CLOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Cannot record a payment against a CLOSED account")
    cust["outstanding_balance_cents"] = cust["outstanding_balance_cents"] - amount
    calc.refresh_customer_status(cust)
    touch(cust)
    return success(public(cust))


@bp.route("/customers/<customerId>/close", methods=["POST"])
def close_customer(customerId):
    _, role = authenticate()
    authorize(role, ["AccountsReceivable"])
    cust = resolve_customer(customerId)
    if cust["status"] == "CLOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Customer account is already CLOSED")
    if cust["outstanding_balance_cents"] != 0:
        raise ApiError(ERR_CUSTOMER_BALANCE_NOT_ZERO, 409, "Close requires outstanding_balance_cents == 0")
    open_charges = [
        c for c in store.charges.values()
        if c.get("customer_id") == cust["id"] and c["status"] not in CHARGE_TERMINAL_STATES
    ]
    if open_charges:
        raise ApiError(ERR_INVALID_STATE, 409, "Close requires no non-terminal Charge referencing this customer")
    cust["status"] = "CLOSED"
    touch(cust)
    return success(public(cust))
