"""Standing order endpoints."""
from flask import Blueprint, request

import clock
import db
import services as svc
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_FACILITY_INACTIVE, ERR_VALIDATION,
    ERR_DUPLICATE_STANDING_ORDER, not_found,
)
from middleware import require_roles, check_facility_ownership
from response import success_object, success_list
from routes_facilities import get_facility_or_404

bp = Blueprint("standing_orders", __name__)

READ_ROLES = ("DistributorAdmin", "FacilityManager", "SalesRep")
WRITE_ROLES = ("FacilityManager", "DistributorAdmin")
FREQUENCIES = ("WEEKLY", "BIWEEKLY", "MONTHLY")


def _pagination():
    try:
        limit = int(request.args.get("limit", "10"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        raise ApiError(ERR_VALIDATION, "limit/offset must be integers", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(ERR_VALIDATION, "limit must be 1..100, offset >= 0", 400)
    return limit, offset


def validate_items(items_raw):
    if not isinstance(items_raw, list) or len(items_raw) == 0:
        raise ApiError(ERR_VALIDATION, "items must be a non-empty array", 400)
    items = []
    for i, entry in enumerate(items_raw):
        if not isinstance(entry, dict):
            raise ApiError(ERR_VALIDATION, "items[%d] must be an object" % i, 400)
        pid = svc.as_str(svc.require_field(entry, "product_id"), "items[%d].product_id" % i)
        qty = svc.as_int(svc.require_field(entry, "qty"), "items[%d].qty" % i, minimum=1)
        # referenced product must exist (priority 4)
        if pid not in db.products:
            raise not_found("Product not found: %s" % pid)
        items.append({"product_id": pid, "qty": qty})
    return items


@bp.post("/jansan/standing-orders")
def create_standing_order():
    user_id, role = require_roles(*WRITE_ROLES)
    body = request.get_json(silent=True) or {}
    facility_id = svc.as_str(svc.require_field(body, "facility_id"), "facility_id")
    check_facility_ownership(user_id, role, facility_id)
    get_facility_or_404(facility_id)
    items = validate_items(svc.require_field(body, "items"))
    frequency = svc.as_enum(svc.require_field(body, "frequency"), "frequency", FREQUENCIES)
    nrd = svc.as_datetime(svc.require_field(body, "next_run_date"), "next_run_date")
    fuel_index = body.get("fuel_index", 3.00)
    fuel_index = svc.as_number(fuel_index, "fuel_index")

    # duplicate standing-order item check (priority 16)
    new_pids = {it["product_id"] for it in items}
    for so in db.standing_orders.values():
        if so["facility_id"] != facility_id:
            continue
        if so["status"] not in ("DRAFT", "ACTIVE", "PAUSED"):
            continue
        existing = {it["product_id"] for it in so["items"]}
        if new_pids & existing:
            raise ApiError(ERR_DUPLICATE_STANDING_ORDER,
                           "Another standing order of this facility shares an item product", 409)

    so = svc.base_resource()
    so.update({
        "facility_id": facility_id,
        "items": items,
        "frequency": frequency,
        "next_run_date": clock.iso_format(nrd),
        "fuel_index": fuel_index,
        "status": "DRAFT",
        "pause_reason": "NONE",
        "price_protected": False,
        "next_delivery_total_cents": 0,
    })
    db.standing_orders[so["id"]] = so
    return success_object(dict(so), 201)


def get_so_or_404(so_id):
    so = db.standing_orders.get(so_id)
    if so is None:
        raise not_found("Standing order not found")
    return so


@bp.get("/jansan/standing-orders/<standing_order_id>")
def get_standing_order(standing_order_id):
    user_id, role = require_roles(*READ_ROLES)
    so = get_so_or_404(standing_order_id)
    check_facility_ownership(user_id, role, so["facility_id"])
    return success_object(dict(so))


@bp.get("/jansan/standing-orders")
def list_standing_orders():
    user_id, role = require_roles(*READ_ROLES)
    facility_id = request.args.get("facility_id")
    status = request.args.get("status")
    limit, offset = _pagination()
    items = list(db.standing_orders.values())
    if role == "FacilityManager":
        items = [s for s in items if s["facility_id"] == user_id]
    if facility_id:
        items = [s for s in items if s["facility_id"] == facility_id]
    if status:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: clock.parse_iso(s["created_at"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([dict(s) for s in page], limit, offset, total)


@bp.post("/jansan/standing-orders/<standing_order_id>/activate")
def activate_standing_order(standing_order_id):
    user_id, role = require_roles(*WRITE_ROLES)
    so = get_so_or_404(standing_order_id)
    check_facility_ownership(user_id, role, so["facility_id"])
    if so["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Standing order is not DRAFT", 409)
    facility = db.facilities.get(so["facility_id"])
    if facility is None or facility["status"] != "ACTIVE":
        raise ApiError(ERR_FACILITY_INACTIVE, "Facility is not ACTIVE", 409)
    if not so["items"]:
        raise ApiError(ERR_VALIDATION, "items must be non-empty", 400)
    so["status"] = "ACTIVE"
    svc.recompute_standing_order_preview(so)
    svc.touch(so)
    return success_object(dict(so))


@bp.post("/jansan/standing-orders/<standing_order_id>/pause")
def pause_standing_order(standing_order_id):
    user_id, role = require_roles(*WRITE_ROLES)
    so = get_so_or_404(standing_order_id)
    check_facility_ownership(user_id, role, so["facility_id"])
    if so["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Standing order is not ACTIVE", 409)
    so["status"] = "PAUSED"
    so["pause_reason"] = "MANUAL"
    svc.touch(so)
    return success_object(dict(so))


@bp.post("/jansan/standing-orders/<standing_order_id>/resume")
def resume_standing_order(standing_order_id):
    user_id, role = require_roles(*WRITE_ROLES)
    so = get_so_or_404(standing_order_id)
    check_facility_ownership(user_id, role, so["facility_id"])
    if so["status"] != "PAUSED":
        raise ApiError(ERR_INVALID_STATE, "Standing order is not PAUSED", 409)
    facility = db.facilities.get(so["facility_id"])
    if facility is None or facility["status"] != "ACTIVE":
        raise ApiError(ERR_FACILITY_INACTIVE, "Facility is not ACTIVE", 409)
    so["status"] = "ACTIVE"
    so["pause_reason"] = "NONE"
    svc.recompute_standing_order_preview(so)
    svc.touch(so)
    return success_object(dict(so))


@bp.post("/jansan/standing-orders/<standing_order_id>/cancel")
def cancel_standing_order(standing_order_id):
    user_id, role = require_roles(*WRITE_ROLES)
    so = get_so_or_404(standing_order_id)
    check_facility_ownership(user_id, role, so["facility_id"])
    if so["status"] not in ("DRAFT", "ACTIVE", "PAUSED"):
        raise ApiError(ERR_INVALID_STATE, "Standing order cannot be cancelled from current state", 409)
    so["status"] = "CANCELLED"
    svc.touch(so)
    return success_object(dict(so))
