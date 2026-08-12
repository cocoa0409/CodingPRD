from flask import Blueprint

import services
from db import bump, create_rec, sorted_ords, store
from errors import ApiError
from middleware import body, require_roles
from response import ok_obj, paginate
from serialize import ser_customer
from validate import req_str

bp = Blueprint("customers", __name__)


def _get_customer(cid):
    c = store.customers.get(cid)
    if c is None:
        raise ApiError("ERR_CUSTOMER_NOT_FOUND", 404, "Customer not found")
    return c


@bp.post("/customers")
def create_customer():
    require_roles("Anonymous")
    b = body()
    full_name = req_str(b, "full_name")
    email = req_str(b, "email")
    phone = req_str(b, "phone")
    if any(c["email"] == email for c in store.customers.values()):
        raise ApiError("ERR_INVALID_REQUEST", 400, "email must be unique across customers")
    rec = create_rec(store.customers, {
        "full_name": full_name, "email": email, "phone": phone,
        "status": "ACTIVE", "risk_score": 0,
        "late_return_count": 0, "captured_damage_count": 0})
    return ok_obj(ser_customer(rec), 201)


@bp.get("/customers/<cid>")
def get_customer(cid):
    uid, role = require_roles("Customer", "OperationsAdmin")
    if role == "Customer" and cid != uid:
        raise ApiError("ERR_FORBIDDEN", 403, "Customers may only read their own record")
    return ok_obj(ser_customer(_get_customer(cid)))


@bp.get("/customers")
def list_customers():
    require_roles("OperationsAdmin")
    recs = sorted_ords(list(store.customers.values()))
    status = __import__("flask").request.args.get("status")
    if status is not None:
        recs = [c for c in recs if c["status"] == status]
    return paginate(recs, ser_customer)


@bp.post("/customers/<cid>/suspend")
def suspend_customer(cid):
    require_roles("OperationsAdmin")
    c = _get_customer(cid)
    if c["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Customer is not ACTIVE")
    c["status"] = "SUSPENDED"
    bump(c)
    return ok_obj(ser_customer(c))


@bp.post("/customers/<cid>/reinstate")
def reinstate_customer(cid):
    require_roles("OperationsAdmin")
    c = _get_customer(cid)
    if c["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Customer is not SUSPENDED")
    c["status"] = "ACTIVE"
    bump(c)
    return ok_obj(ser_customer(c))
