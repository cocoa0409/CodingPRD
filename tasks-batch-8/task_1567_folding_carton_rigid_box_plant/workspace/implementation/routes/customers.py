"""Customer endpoints (PRD §3.1)."""

from flask import Blueprint

import db
from errors import ApiError, ERR_INVALID_STATE_TRANSITION
from middleware import ALL_ROLES, authenticate
from response import ok_object
from routes.common import (
    get_body,
    get_or_404,
    list_response,
    req_enum,
    req_str,
    ser_plain,
)
from util import touch

bp = Blueprint("customers", __name__)

CUSTOMER_STATUSES = ("ACTIVE", "SUSPENDED")


@bp.post("/plant/customers")
def create_customer():
    authenticate(("PlantAdmin",))
    data = get_body()
    name = req_str(data, "name")
    brand_code = req_str(data, "brand_code")
    rec = db.new_record()
    rec.update({"name": name, "brand_code": brand_code, "status": "ACTIVE"})
    db.customers[rec["id"]] = rec
    return ok_object(ser_plain(rec), 201)


@bp.get("/plant/customers")
def list_customers():
    authenticate(ALL_ROLES)
    return list_response(db.customers.values(), ser_plain, [("status", "status", "str")])


@bp.get("/plant/customers/<customerId>")
def get_customer(customerId):
    authenticate(ALL_ROLES)
    return ok_object(ser_plain(get_or_404(db.customers, customerId)))


@bp.post("/plant/customers/<customerId>/set-status")
def set_customer_status(customerId):
    authenticate(("PlantAdmin",))
    rec = get_or_404(db.customers, customerId)
    data = get_body()
    to_status = req_enum(data, "to_status", CUSTOMER_STATUSES)
    if to_status == rec["status"]:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Customer is already %s" % to_status)
    rec["status"] = to_status
    touch(rec)
    return ok_object(ser_plain(rec))
