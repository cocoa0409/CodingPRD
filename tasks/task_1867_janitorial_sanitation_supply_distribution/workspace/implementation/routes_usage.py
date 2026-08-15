"""Usage record endpoints."""
from flask import Blueprint, request

import clock
import db
import services as svc
from errors import ApiError, ERR_INVALID_STATE, ERR_FACILITY_INACTIVE, not_found
from middleware import require_roles, check_facility_ownership
from response import success_object, success_list
from routes_facilities import get_facility_or_404
from routes_products import get_product_or_404

bp = Blueprint("usage_records", __name__)

READ_ROLES = ("DistributorAdmin", "FacilityManager", "SalesRep")
SOURCES = ("MANUAL", "AUTO_DISPENSER")


def view(r):
    return dict(r)


@bp.post("/jansan/usage-records")
def create_usage_record():
    user_id, role = require_roles("FacilityManager", "DistributorAdmin")
    body = request.get_json(silent=True) or {}
    facility_id = svc.as_str(svc.require_field(body, "facility_id"), "facility_id")
    product_id = svc.as_str(svc.require_field(body, "product_id"), "product_id")
    check_facility_ownership(user_id, role, facility_id)
    facility = get_facility_or_404(facility_id)
    get_product_or_404(product_id)
    ps_raw = svc.require_field(body, "period_start")
    pe_raw = svc.require_field(body, "period_end")
    ps = svc.as_datetime(ps_raw, "period_start")
    pe = svc.as_datetime(pe_raw, "period_end")
    if pe < ps:
        raise ApiError("ERR_VALIDATION", "period_end must be >= period_start", 400)
    qty = svc.as_int(svc.require_field(body, "quantity_used"), "quantity_used", minimum=1)
    source = svc.as_enum(svc.require_field(body, "source"), "source", SOURCES)
    # facility gate (priority 8)
    if facility["status"] != "ACTIVE":
        raise ApiError(ERR_FACILITY_INACTIVE, "Facility is not ACTIVE", 409)

    r = svc.base_resource()
    r.update({
        "facility_id": facility_id,
        "product_id": product_id,
        "period_start": clock.iso_format(ps),
        "period_end": clock.iso_format(pe),
        "quantity_used": qty,
        "source": source,
        "status": "SUBMITTED",
        "posted_at": None,
    })
    db.usage_records[r["id"]] = r
    return success_object(view(r), 201)


@bp.get("/jansan/usage-records/<usage_record_id>")
def get_usage_record(usage_record_id):
    user_id, role = require_roles(*READ_ROLES)
    r = db.usage_records.get(usage_record_id)
    if r is None:
        raise not_found("Usage record not found")
    check_facility_ownership(user_id, role, r["facility_id"])
    return success_object(view(r))


@bp.get("/jansan/usage-records")
def list_usage_records():
    user_id, role = require_roles(*READ_ROLES)
    facility_id = request.args.get("facility_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    limit, offset = _pagination()
    items = list(db.usage_records.values())
    if role == "FacilityManager":
        items = [r for r in items if r["facility_id"] == user_id]
    if facility_id:
        items = [r for r in items if r["facility_id"] == facility_id]
    if product_id:
        items = [r for r in items if r["product_id"] == product_id]
    if status:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: clock.parse_iso(r["created_at"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([view(r) for r in page], limit, offset, total)


def _pagination():
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise ApiError("ERR_VALIDATION", "limit/offset must be integers", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError("ERR_VALIDATION", "limit must be 1..100, offset >= 0", 400)
    return limit, offset


@bp.post("/jansan/usage-records/<usage_record_id>/post")
def post_usage_record(usage_record_id):
    require_roles("DistributorAdmin")
    r = db.usage_records.get(usage_record_id)
    if r is None:
        raise not_found("Usage record not found")
    if r["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Usage record is not SUBMITTED", 409)
    r["status"] = "POSTED"
    r["posted_at"] = clock.iso_now()
    svc.touch(r)
    return success_object(view(r))
