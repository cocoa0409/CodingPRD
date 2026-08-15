"""Customer endpoints."""
from flask import Blueprint

import db
import errors
from middleware import (
    authenticate,
    body,
    req_enum,
    req_str,
    require_role,
)
from response import success
from serializers import ser_customer

bp = Blueprint("customers", __name__)

CUSTOMER_KINDS = {"INDIVIDUAL", "FLIGHT_SCHOOL", "FLEET_OPERATOR"}


@bp.post("/avionics/customers")
def create_customer():
    _, role = authenticate()
    require_role(role, {"ShopManager"})
    b = body()
    name = req_str(b, "name")
    contact_email = req_str(b, "contact_email")
    kind = "INDIVIDUAL"
    if b.get("customer_kind") is not None:
        kind = req_enum(b, "customer_kind", CUSTOMER_KINDS)
    c = db.new_entity(name=name, contact_email=contact_email, customer_kind=kind)
    db.customers[c.id] = c
    return success(ser_customer(c), 201)


@bp.get("/avionics/customers/<customerId>")
def get_customer(customerId):
    authenticate()
    c = db.customers.get(customerId)
    if c is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "Customer not found")
    return success(ser_customer(c), 200)
