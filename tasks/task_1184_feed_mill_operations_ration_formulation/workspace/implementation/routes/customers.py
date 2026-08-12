"""Customers: registration, credit/permit adjustment with OCC, suspension (PRD 3.5)."""
from flask import Blueprint

from db import STORE, make_record, bump
from envelope import success
from errors import ApiError
from middleware import authenticate, authorize
from services import ser_customer
from validation import get_body, req_str, req_int, opt_str_nullable, req_enum, MISSING

bp = Blueprint("customers", __name__)


def _get_customer(cid):
    c = STORE["customers"].get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Customer {cid} not found")
    return c


@bp.post("/api/customers")
def create_customer():
    uid, role = authenticate()
    data = get_body()
    name = req_str(data, "name")
    credit_limit = req_int(data, "credit_limit_cents", gt=0)
    permit = opt_str_nullable(data, "medicated_permit_ref", None)
    authorize(role, uid, {"MillManager"})
    rec = make_record()
    rec.update(name=name, credit_limit_cents=credit_limit,
               medicated_permit_ref=permit, status="ACTIVE")
    STORE["customers"][rec["id"]] = rec
    return success(ser_customer(rec), 201)


@bp.get("/api/customers/<cid>")
def get_customer(cid):
    uid, role = authenticate()
    authorize(role, uid, {"MillManager", "Customer"})
    # Customer-role callers may read only their own record; a foreign id
    # resolves exactly as if the resource did not exist (PRD 2.1).
    if role == "Customer" and cid != uid:
        raise ApiError("ERR_NOT_FOUND", 404, f"Customer {cid} not found")
    return success(ser_customer(_get_customer(cid)), 200)


@bp.patch("/api/customers/<cid>")
def patch_customer(cid):
    uid, role = authenticate()
    data = get_body()
    credit_limit = MISSING
    if "credit_limit_cents" in data:
        credit_limit = req_int(data, "credit_limit_cents", gt=0)
    permit = MISSING
    if "medicated_permit_ref" in data:
        permit = opt_str_nullable(data, "medicated_permit_ref")
    expected = req_int(data, "expected_customer_version")
    authorize(role, uid, {"MillManager"})
    c = _get_customer(cid)
    if expected != c["version"]:
        raise ApiError("ERR_STALE_CUSTOMER_VERSION", 412,
                       "expected_customer_version does not match the customer's version")
    if credit_limit is not MISSING:
        c["credit_limit_cents"] = credit_limit
    if permit is not MISSING:
        c["medicated_permit_ref"] = permit
    bump(c)
    return success(ser_customer(c), 200)


@bp.post("/api/customers/<cid>/set-status")
def set_customer_status(cid):
    uid, role = authenticate()
    data = get_body()
    status = req_enum(data, "status", ("ACTIVE", "SUSPENDED"))
    authorize(role, uid, {"MillManager"})
    c = _get_customer(cid)
    if c["status"] == status:
        raise ApiError("ERR_INVALID_STATE", 409, f"Customer is already {status}")
    c["status"] = status
    bump(c)
    return success(ser_customer(c), 200)
