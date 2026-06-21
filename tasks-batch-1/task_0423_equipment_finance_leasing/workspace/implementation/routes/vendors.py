"""Vendor endpoints — PRD §3.1, §4."""
from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_roles, ALL_ROLES
from response import object_response, array_response
from services.common import (
    get_json_body, require_string, serialize, paginate, sort_by_created,
)
from services import domain

bp = Blueprint("vendors", __name__)


@bp.post("/lessors/<lessor_id>/vendors")
def create_vendor(lessor_id):
    user_id, role = get_user_context()
    require_roles(role, ["FundingOfficer"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        body = get_json_body()
        name = require_string(body, "name")
        remit_account = require_string(body, "remit_account")
        rec = db.init_record({
            "lessor_id": lessor_id,
            "name": name,
            "remit_account": remit_account,
            "status": "PENDING",
        })
        db.vendors[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.get("/lessors/<lessor_id>/vendors/<vendor_id>")
def get_vendor(lessor_id, vendor_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_vendor(lessor_id, vendor_id)
        return object_response(serialize(rec), 200)


@bp.get("/lessors/<lessor_id>/vendors")
def list_vendors(lessor_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        items = [v for v in db.vendors.values() if v["lessor_id"] == lessor_id]
        status = request.args.get("status")
        if status is not None and status != "":
            items = [v for v in items if v["status"] == status]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


@bp.post("/lessors/<lessor_id>/vendors/<vendor_id>/approve")
def approve_vendor(lessor_id, vendor_id):
    user_id, role = get_user_context()
    require_roles(role, ["FundingOfficer"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_vendor(lessor_id, vendor_id)
        # APPROVED reachable from PENDING or SUSPENDED.
        if rec["status"] not in ("PENDING", "SUSPENDED"):
            raise errors.invalid_state("Vendor not in a state that can be approved")
        rec["status"] = "APPROVED"
        db.touch(rec)
        return object_response(serialize(rec), 200)


@bp.post("/lessors/<lessor_id>/vendors/<vendor_id>/suspend")
def suspend_vendor(lessor_id, vendor_id):
    user_id, role = get_user_context()
    require_roles(role, ["FundingOfficer"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_vendor(lessor_id, vendor_id)
        if rec["status"] != "APPROVED":
            raise errors.invalid_state("Only an APPROVED vendor can be suspended")
        rec["status"] = "SUSPENDED"
        db.touch(rec)
        return object_response(serialize(rec), 200)
