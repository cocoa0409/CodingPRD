"""Work-order pipeline: SUBMITTED -> DISPATCHED -> IN_PROGRESS -> RESOLVED -> CONFIRMED
plus REJECTED, CANCELLED, and the reopen branch."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g

import db
from errors import (
    APIError,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_RATING_OUT_OF_RANGE,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VALIDATION,
)
from middleware import require_roles
from response import success
from services.common import bump, stamp_create
from utils import get_body, iso_format, require_field

bp = Blueprint("work_orders", __name__)

VALID_CATEGORIES = {"PLUMBING", "ELECTRICAL", "STRUCTURAL", "LANDSCAPING", "SECURITY", "OTHER"}


def _get_or_404(wid):
    wo = db.work_orders.get(wid)
    if wo is None:
        raise APIError(ERR_NOT_FOUND, f"WorkOrder {wid} not found.", 404)
    return wo


@bp.post("/work-orders")
@require_roles("Owner")
def create_work_order():
    body = get_body()
    property_id = require_field(body, "property_id")
    category = require_field(body, "category")
    location_tag = require_field(body, "location_tag")
    photo_urls = body.get("photo_urls", [])

    prop = db.properties.get(property_id)
    if prop is None:
        raise APIError(ERR_REFERENCE_NOT_FOUND, f"Property {property_id} not found.", 404)
    # Owner must own the property
    if prop.get("owner_id") != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Owner does not own this property.", 403)

    if category not in VALID_CATEGORIES:
        raise APIError(ERR_VALIDATION, "Invalid category.", 422)
    if not isinstance(photo_urls, list):
        raise APIError(ERR_VALIDATION, "photo_urls must be a list.", 422)

    wo = {
        "property_id": property_id,
        "reporter_owner_id": g.user_id,
        "category": category,
        "location_tag": location_tag,
        "photo_urls": photo_urls,
        "status": "SUBMITTED",
        "assigned_staff_id": None,
        "resolved_at": None,
        "confirm_deadline_at": None,
        "satisfaction_score": None,
    }
    stamp_create(wo)
    db.work_orders[wo["id"]] = wo
    return success(wo, status=201)


@bp.post("/work-orders/<wid>/dispatch")
@require_roles("PropertyManager")
def dispatch(wid):
    wo = _get_or_404(wid)
    body = get_body()
    assigned_staff_id = require_field(body, "assigned_staff_id")
    if wo["status"] != "SUBMITTED":
        raise APIError(ERR_INVALID_STATE, "Work order is not SUBMITTED.", 409)
    wo["assigned_staff_id"] = assigned_staff_id
    wo["status"] = "DISPATCHED"
    bump(wo)
    return success(wo)


@bp.post("/work-orders/<wid>/start")
@require_roles("MaintenanceStaff")
def start(wid):
    wo = _get_or_404(wid)
    if wo["status"] != "DISPATCHED":
        raise APIError(ERR_INVALID_STATE, "Work order is not DISPATCHED.", 409)
    if wo.get("assigned_staff_id") != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Only assigned staff may start.", 403)
    wo["status"] = "IN_PROGRESS"
    bump(wo)
    return success(wo)


@bp.post("/work-orders/<wid>/reject")
@require_roles("MaintenanceStaff")
def reject(wid):
    wo = _get_or_404(wid)
    body = get_body()
    rejection_reason = require_field(body, "rejection_reason")
    if wo["status"] != "DISPATCHED":
        raise APIError(ERR_INVALID_STATE, "Work order is not DISPATCHED.", 409)
    if wo.get("assigned_staff_id") != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Only assigned staff may reject.", 403)
    wo["status"] = "REJECTED"
    wo["rejection_reason"] = rejection_reason
    bump(wo)
    return success(wo)


@bp.post("/work-orders/<wid>/resolve")
@require_roles("MaintenanceStaff")
def resolve(wid):
    wo = _get_or_404(wid)
    if wo["status"] != "IN_PROGRESS":
        raise APIError(ERR_INVALID_STATE, "Work order is not IN_PROGRESS.", 409)
    if wo.get("assigned_staff_id") != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Only assigned staff may resolve.", 403)
    now = db.now()
    wo["resolved_at"] = iso_format(now)
    wo["confirm_deadline_at"] = iso_format(now + timedelta(hours=72))
    wo["status"] = "RESOLVED"
    bump(wo)
    return success(wo)


@bp.post("/work-orders/<wid>/confirm")
@require_roles("Owner")
def confirm(wid):
    wo = _get_or_404(wid)
    if wo["status"] != "RESOLVED":
        raise APIError(ERR_INVALID_STATE, "Work order is not RESOLVED.", 409)
    if wo.get("reporter_owner_id") != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Only the reporter may confirm.", 403)
    body = get_body()
    score = require_field(body, "satisfaction_score")
    if not isinstance(score, int) or score < 1 or score > 5:
        raise APIError(ERR_RATING_OUT_OF_RANGE, "satisfaction_score must be in [1,5].", 422)
    wo["satisfaction_score"] = score
    wo["status"] = "CONFIRMED"
    bump(wo)
    return success(wo)


@bp.post("/work-orders/<wid>/reopen")
@require_roles("Owner")
def reopen(wid):
    wo = _get_or_404(wid)
    if wo["status"] != "RESOLVED":
        raise APIError(ERR_INVALID_STATE, "Work order is not RESOLVED.", 409)
    if wo.get("reporter_owner_id") != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Only the reporter may reopen.", 403)
    deadline_str = wo.get("confirm_deadline_at")
    from utils import parse_iso
    if not deadline_str or db.now() >= parse_iso(deadline_str, field="confirm_deadline_at"):
        raise APIError(ERR_INVALID_STATE, "Reopen window has elapsed.", 409)
    wo["assigned_staff_id"] = None
    wo["resolved_at"] = None
    wo["confirm_deadline_at"] = None
    wo["status"] = "SUBMITTED"
    bump(wo)  # PRD §3.2: bump version on revision cycle
    return success(wo)


@bp.post("/work-orders/<wid>/cancel")
@require_roles("Owner")
def cancel(wid):
    wo = _get_or_404(wid)
    if wo["status"] != "SUBMITTED":
        raise APIError(ERR_INVALID_STATE, "Work order is not SUBMITTED.", 409)
    if wo.get("reporter_owner_id") != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Only the reporter may cancel.", 403)
    wo["status"] = "CANCELLED"
    bump(wo)
    return success(wo)
