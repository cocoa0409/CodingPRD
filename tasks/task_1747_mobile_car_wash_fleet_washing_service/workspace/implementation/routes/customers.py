"""Customer endpoints."""

from flask import Blueprint

from db import store
from serialize import ser_customer
from util import (
    caller, require_role, forbid, get_body, respond, req_str, opt_enum,
    stamp_new, touch, ApiError,
)
from errors import ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE

bp = Blueprint("customers", __name__)

CUSTOMER_TYPES = {"RETAIL", "FLEET"}


@bp.post("/fleet-wash/customers")
def create_customer():
    _uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    name = req_str(body, "name")
    email = req_str(body, "email")
    ctype = opt_enum(body, "customer_type", CUSTOMER_TYPES, "RETAIL")
    for c in store.customers.values():
        if c["email"] == email:
            raise ApiError(ERR_VALIDATION, "email must be unique across customers")
    rec = {"name": name, "email": email, "customer_type": ctype, "status": "ACTIVE"}
    stamp_new(rec)
    store.customers[rec["id"]] = rec
    return respond(ser_customer(rec), 201)


@bp.get("/fleet-wash/customers/<cid>")
def get_customer(cid):
    uid, role = caller()
    rec = store.customers.get(cid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "Customer %s not found" % cid)
    if role == "Customer" and uid != cid:
        forbid("Customers may only access their own record")
    return respond(ser_customer(rec), 200)


@bp.post("/fleet-wash/customers/<cid>/events")
def customer_event(cid):
    _uid, role = caller()
    require_role(role, {"PlatformAdmin"})
    rec = store.customers.get(cid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "Customer %s not found" % cid)
    body = get_body()
    event = req_str(body, "event_type")
    if event not in ("SUSPEND", "REACTIVATE"):
        raise ApiError(ERR_VALIDATION, "event_type must be SUSPEND or REACTIVATE")
    if event == "SUSPEND":
        if rec["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "Customer is not ACTIVE")
        rec["status"] = "SUSPENDED"
    else:
        if rec["status"] != "SUSPENDED":
            raise ApiError(ERR_INVALID_STATE, "Customer is not SUSPENDED")
        rec["status"] = "ACTIVE"
    touch(rec)
    return respond(ser_customer(rec), 200)
