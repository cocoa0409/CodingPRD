from flask import Blueprint

from db import STORE, make_rec
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import ok_object
from serializers import customer as ser
from validate import require_roles, body, req_str

bp = Blueprint("customers", __name__)


@bp.post("/revrec/customers")
def create_customer():
    require_roles("RevenueAccountant")
    data = body()
    legal_name = req_str(data, "legal_name")
    external_ref = req_str(data, "external_ref")
    for c in STORE.customers.values():
        if c["external_ref"] == external_ref:
            raise ApiError(ERR_INVALID_REQUEST, 400, "external_ref must be unique per customer")
    rec = make_rec(STORE.customers, {"legal_name": legal_name, "external_ref": external_ref})
    return ok_object(ser(rec), 201)


@bp.get("/revrec/customers/<customer_id>")
def get_customer(customer_id):
    require_roles("RevenueAccountant", "RevenueManager", "ContractReviewer", "Controller")
    rec = STORE.customers.get(customer_id)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, 404, "customer_id does not identify an existing customer")
    return ok_object(ser(rec))
