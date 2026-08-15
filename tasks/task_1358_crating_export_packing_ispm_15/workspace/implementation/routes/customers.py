"""Customer endpoints (PRD §3.1, §4)."""
from flask import Blueprint

from db import STORE, new_id, now_iso, touch
from errors import ApiError, ERR_DUPLICATE, ERR_INVALID_STATE, not_found
from middleware import (ALL_OPERATIONAL, require_roles, body, req_str, req_int,
                        opt_str, opt_int, paginate, enum_filter)
from response import success
from services.state import get, ser_customer

bp = Blueprint("customers", __name__)

STAFF_ROLES = ["SalesRep", "CratingDesigner", "ShopForeman",
               "ComplianceOfficer", "LogisticsCoordinator", "ClaimsAdjuster"]


@bp.post("/crating/customers")
def create_customer():
    require_roles(["SalesRep"])
    d = body()
    name = req_str(d, "name")
    site_code = req_str(d, "site_code")
    credit_limit_cents = req_int(d, "credit_limit_cents", minimum=0)
    # uniqueness (PRD §2.9): site_code unique across customers
    for c in STORE["customers"].values():
        if c["site_code"] == site_code:
            raise ApiError(ERR_DUPLICATE, "site_code already exists", 409)
    rec = {
        "id": new_id(), "name": name, "site_code": site_code,
        "credit_limit_cents": credit_limit_cents, "status": "ACTIVE",
        "created_at": now_iso(), "updated_at": now_iso(), "version": 1,
    }
    STORE["customers"][rec["id"]] = rec
    return success(ser_customer(rec), status=201)


@bp.get("/crating/customers/<cid>")
def get_customer(cid):
    require_roles(ALL_OPERATIONAL)
    c = get("customers", cid)
    if not c:
        raise not_found("Customer not found")
    return success(ser_customer(c))


@bp.get("/crating/customers")
def list_customers():
    require_roles(STAFF_ROLES)
    status = enum_filter("status", {"ACTIVE", "SUSPENDED"})
    recs = [c for c in STORE["customers"].values()
            if status is None or c["status"] == status]
    recs.sort(key=lambda c: c["created_at"])
    page, meta = paginate(recs)
    return success([ser_customer(c) for c in page], pagination=meta)


@bp.patch("/crating/customers/<cid>")
def patch_customer(cid):
    require_roles(["SalesRep"])
    d = body()
    name = opt_str(d, "name")
    credit_limit_cents = opt_int(d, "credit_limit_cents", minimum=0)
    c = get("customers", cid)
    if not c:
        raise not_found("Customer not found")
    if name is not None:
        c["name"] = name
    if credit_limit_cents is not None:
        c["credit_limit_cents"] = credit_limit_cents
    touch(c)
    return success(ser_customer(c))


@bp.post("/crating/customers/<cid>/suspend")
def suspend_customer(cid):
    require_roles(["SalesRep"])
    c = get("customers", cid)
    if not c:
        raise not_found("Customer not found")
    if c["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Only an ACTIVE customer can be suspended", 409)
    c["status"] = "SUSPENDED"
    touch(c)
    return success(ser_customer(c))


@bp.post("/crating/customers/<cid>/reinstate")
def reinstate_customer(cid):
    require_roles(["SalesRep"])
    c = get("customers", cid)
    if not c:
        raise not_found("Customer not found")
    if c["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "Only a SUSPENDED customer can be reinstated", 409)
    c["status"] = "ACTIVE"
    touch(c)
    return success(ser_customer(c))
