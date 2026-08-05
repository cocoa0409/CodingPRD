from flask import Blueprint

import store
from store import DB
from core import (get_auth, require_role, get_body, require_fields, check_enum,
                  ok, ok_list, paginate, sorted_records, base_record, deny)
from serializers import ser_customer
from domain import get_customer

bp = Blueprint("customers", __name__)


@bp.post("/customers")
def create_customer():
    uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["name", "email", "customer_type"])
    check_enum(body["customer_type"], {"INDIVIDUAL", "FLEET"}, "customer_type")
    if not isinstance(body["name"], str) or not isinstance(body["email"], str):
        from core import ApiError
        raise ApiError("ERR_VALIDATION", "name/email must be strings")
    rec = base_record()
    rec.update({
        "name": body["name"],
        "email": body["email"],
        "customer_type": body["customer_type"],
        "status": "ACTIVE",
    })
    DB.customers[rec["id"]] = rec
    return ok(ser_customer(rec), status=201)


@bp.get("/customers")
def list_customers():
    uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "BillingOfficer"})
    from flask import request
    items = sorted_records(DB.customers)
    ct = request.args.get("customer_type")
    st = request.args.get("status")
    if ct:
        items = [c for c in items if c["customer_type"] == ct]
    if st:
        items = [c for c in items if c["status"] == st]
    page, total, limit, offset = paginate(items)
    return ok_list([ser_customer(c) for c in page], total, limit, offset)


@bp.get("/customers/<cid>")
def get_customer_ep(cid):
    uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "BillingOfficer", "FleetManager", "Member"})
    c = get_customer(cid)
    if role in ("Member", "FleetManager") and c["id"] != uid:
        deny()
    return ok(ser_customer(c))
