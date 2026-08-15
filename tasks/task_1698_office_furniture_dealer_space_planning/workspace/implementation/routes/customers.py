"""Customer routes: onboarding, credit hold lifecycle, settled close."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_INVALID_STATE,
    ERR_CUSTOMER_NOT_SETTLED,
    ERR_DUPLICATE_REFERENCE,
)
from middleware import ALL_ROLES
from response import success_object
from routes.helpers import authorize, list_response, get_response
from serialize import public
from services.core import get_or_404, new_entity, touch
from validate import body_dict, req_str

bp = Blueprint("customers", __name__)

OPEN_ORDER_STATUSES = {"DRAFT", "SUBMITTED", "ACKNOWLEDGED", "DELIVERED", "INSTALLED"}


@bp.route("/api/customers", methods=["POST"])
def create_customer():
    authorize(["AccountExecutive"])
    body = body_dict()
    dealership_id = req_str(body, "dealership_id")
    name = req_str(body, "name")
    external_ref = req_str(body, "external_ref")
    # priority 3: FK existence
    get_or_404("dealerships", dealership_id)
    # priority 8c: external_ref unique per dealership
    for other in db["customers"].values():
        if other["dealership_id"] == dealership_id and other["external_ref"] == external_ref:
            raise_error(ERR_DUPLICATE_REFERENCE,
                        f"external_ref '{external_ref}' already exists in dealership {dealership_id}")
    customer = new_entity("customers", {
        "dealership_id": dealership_id,
        "name": name,
        "external_ref": external_ref,
        "status": "ACTIVE",
        "liquidation_credit_balance_cents": 0,
        "_fee_debits": 0,
    })
    return success_object(public(customer), status=201)


@bp.route("/api/customers", methods=["GET"])
def list_customers():
    authorize(ALL_ROLES)
    return list_response("customers", ["dealership_id", "status"])


@bp.route("/api/customers/<customer_id>", methods=["GET"])
def get_customer(customer_id):
    authorize(ALL_ROLES)
    return get_response("customers", customer_id)


@bp.route("/api/customers/<customer_id>/hold", methods=["POST"])
def hold_customer(customer_id):
    authorize(["AccountExecutive"])
    customer = get_or_404("customers", customer_id)
    if customer["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, f"cannot hold a customer in status {customer['status']}")
    customer["status"] = "CREDIT_HOLD"
    touch(customer)
    return success_object(public(customer))


@bp.route("/api/customers/<customer_id>/release_hold", methods=["POST"])
def release_hold_customer(customer_id):
    authorize(["AccountExecutive"])
    customer = get_or_404("customers", customer_id)
    if customer["status"] != "CREDIT_HOLD":
        raise_error(ERR_INVALID_STATE, f"cannot release hold on a customer in status {customer['status']}")
    customer["status"] = "ACTIVE"
    touch(customer)
    return success_object(public(customer))


@bp.route("/api/customers/<customer_id>/close", methods=["POST"])
def close_customer(customer_id):
    authorize(["AccountExecutive"])
    customer = get_or_404("customers", customer_id)
    if customer["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, f"cannot close a customer in status {customer['status']}")
    if customer["liquidation_credit_balance_cents"] != 0:
        raise_error(ERR_CUSTOMER_NOT_SETTLED, "customer credit balance is nonzero")
    open_orders = [
        o for o in db["project_orders"].values()
        if o["customer_id"] == customer_id and o["status"] in OPEN_ORDER_STATUSES
    ]
    if open_orders:
        raise_error(ERR_CUSTOMER_NOT_SETTLED, "customer has unsettled project orders")
    customer["status"] = "CLOSED"
    touch(customer)
    return success_object(public(customer))
