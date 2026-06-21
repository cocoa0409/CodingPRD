"""Customer endpoints."""
from flask import Blueprint, request, g

from db import db, new_id, now_iso
from errors import err
from response import success, list_response
from middleware import require_roles
from common import (get_json, require_fields, require_str, fk_or_404, get_or_404,
                    touch, parse_pagination, paginate, require_customer_owns)
import serializers as S

bp = Blueprint("customers", __name__)


@bp.post("/customers")
def create_customer():
    require_roles("FacilityOperator", "Customer")
    body = get_json()
    require_fields(body, ["facility_id", "full_name", "email", "phone"])
    facility_id = require_str(body, "facility_id")
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    phone = require_str(body, "phone")
    fk_or_404(db.facilities, facility_id)
    for c in db.customers.values():
        if c["facility_id"] == facility_id and c["email"] == email:
            raise err("ERR_DUPLICATE", "email already exists in facility")
    cid = new_id()
    customer = {
        "id": cid,
        "facility_id": facility_id,
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "status": "ACTIVE",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.customers[cid] = customer
    return success(S.customer_out(customer), status=201)


@bp.get("/customers/<cid>")
def get_customer(cid):
    require_roles("FacilityOperator", "ComplianceOfficer", "Customer")
    customer = get_or_404(db.customers, cid)
    require_customer_owns(customer["id"])
    return success(S.customer_out(customer))


@bp.get("/customers")
def list_customers():
    require_roles("FacilityOperator", "ComplianceOfficer")
    limit, offset = parse_pagination()
    items = list(db.customers.values())
    fid = request.args.get("facility_id")
    status = request.args.get("status")
    if fid is not None:
        items = [x for x in items if x["facility_id"] == fid]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response([S.customer_out(x) for x in page], limit, offset, total)


@bp.post("/customers/<cid>/suspend")
def suspend_customer(cid):
    require_roles("FacilityOperator", "ComplianceOfficer")
    customer = get_or_404(db.customers, cid)
    if customer["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Customer must be ACTIVE to suspend")
    customer["status"] = "SUSPENDED"
    touch(customer)
    return success(S.customer_out(customer))
