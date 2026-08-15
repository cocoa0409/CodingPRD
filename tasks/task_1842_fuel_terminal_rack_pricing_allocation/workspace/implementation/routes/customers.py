from flask import Blueprint, request

from db import db
from errors import (
    ApiError, ERR_CUSTOMER_NOT_ON_HOLD, ERR_INVALID_STATE, not_found,
)
from helpers import (
    get_body, list_query, new_entity, ser_customer, touch,
)
from middleware import require_roles
from response import success_list, success_object
from services import log_credit_event, place_hold

bp = Blueprint("customers", __name__)

_GET_ROLES = [
    "PlatformAdmin", "CreditAnalyst", "BillingClerk",
    "ContractAdministrator", "TerminalOperator",
]
_LIST_ROLES = [
    "PlatformAdmin", "CreditAnalyst", "BillingClerk", "ContractAdministrator",
]


def _get_customer(customer_id):
    c = db.customers.get(customer_id)
    if c is None:
        raise not_found("Customer {} does not exist".format(customer_id))
    return c


@bp.post("/rack/customers")
def create_customer():
    require_roles(["PlatformAdmin"])
    body = get_body()
    c = new_entity({
        "customer_code": body.get("customer_code"),
        "legal_name": body.get("legal_name"),
        "credit_limit_cents": body.get("credit_limit_cents", 0),
        "open_lifting_exposure_cents": 0,
        "credit_status": "GOOD",
        "hold_reason": None,
    })
    db.customers[c["id"]] = c
    return success_object(ser_customer(c), 201)


@bp.get("/rack/customers/<customerId>")
def get_customer(customerId):
    require_roles(_GET_ROLES)
    return success_object(ser_customer(_get_customer(customerId)))


@bp.get("/rack/customers")
def list_customers():
    require_roles(_LIST_ROLES)
    page, total, limit, offset = list_query(
        db.customers.values(), request.args, ["credit_status"]
    )
    return success_list([ser_customer(c) for c in page], total, limit, offset)


@bp.post("/rack/customers/<customerId>/place-hold")
def place_customer_hold(customerId):
    require_roles(["CreditAnalyst"])
    c = _get_customer(customerId)
    if c["credit_status"] != "GOOD":
        raise ApiError(
            ERR_INVALID_STATE, 409,
            "Customer must be in GOOD standing to place a hold",
        )
    reason = get_body().get("reason")
    place_hold(c, reason, "MANUAL")
    return success_object(ser_customer(c))


@bp.post("/rack/customers/<customerId>/release-hold")
def release_customer_hold(customerId):
    require_roles(["CreditAnalyst"])
    c = _get_customer(customerId)
    if c["credit_status"] != "HOLD":
        raise ApiError(
            ERR_CUSTOMER_NOT_ON_HOLD, 409,
            "Customer must be in HOLD to release the hold",
        )
    c["credit_status"] = "GOOD"
    c["hold_reason"] = None
    touch(c)
    log_credit_event(c, "RELEASED", "RELEASED")
    return success_object(ser_customer(c))
