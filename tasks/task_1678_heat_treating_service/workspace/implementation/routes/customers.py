"""CustomerAccount endpoints."""
from flask import Blueprint

import validation as v
from db import store, new_id, new_common
from errors import ApiError
from middleware import ANY_ROLES, get_context, require_roles
from response import created, ok
from services import domain

bp = Blueprint("customers", __name__)


@bp.post("/customer-accounts")
def create_customer():
    get_context()
    require_roles(["CustomerServiceRep"])
    body = v.get_body()
    # tier 9: required fields / enum validity
    name = v.req_string(body, "name")
    tier = v.opt_enum(body, "liability_tier", domain.LIABILITY_TIERS, default="STANDARD")
    credit_hold = v.opt_bool(body, "credit_hold", default=False)
    customer = {
        "id": new_id(),
        "name": name,
        "liability_tier": tier,
        "credit_hold": credit_hold,
        "outstanding_liability_exposure_cents": 0,
    }
    new_common(customer)
    store.customers[customer["id"]] = customer
    return created(customer)


@bp.get("/customer-accounts/<customer_id>")
def get_customer(customer_id):
    get_context()
    require_roles(ANY_ROLES)
    customer = store.customers.get(customer_id)
    if customer is None:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", 404, "CustomerAccount not found")
    return ok(customer)
