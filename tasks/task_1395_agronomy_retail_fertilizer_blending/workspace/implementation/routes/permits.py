"""EnvironmentalPermit routes with revoke cascade."""

from flask import Blueprint, request

import db
from errors import not_found, invalid_transition, validation
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, iso8601_ms
from services.core import scaffold_entity, touch, public, lazy_permit, now_stamp_helper
from util import (
    get_body, require, optional, reject_unknown, as_string, as_enum, as_int,
    as_number, parse_pagination, paginate, parse_instant,
)

bp = Blueprint("permits", __name__)

PERMIT_TYPES = {"FERTILIZER_STORAGE", "BLENDER_SITE", "ANHYDROUS_STORAGE"}


def _get_permit(pid):
    x = db.permits.get(pid)
    if x is None:
        raise not_found("Permit not found")
    return x


@bp.post("/agronomy/environmental-permits")
def create_permit():
    require_roles("ComplianceOfficer")
    body = get_body()
    reject_unknown(body, {"permit_type", "site_code", "setback_ft", "max_storage_tons"})
    ptype = as_enum(require(body, "permit_type"), "permit_type", PERMIT_TYPES)
    site_code = as_string(require(body, "site_code"), "site_code")
    setback = as_int(require(body, "setback_ft"), "setback_ft", minimum=1)
    max_storage = optional(body, "max_storage_tons", None)
    if ptype == "FERTILIZER_STORAGE":
        if max_storage is None:
            raise validation("max_storage_tons required for FERTILIZER_STORAGE")
        max_storage = float(as_number(max_storage, "max_storage_tons", minimum=0, exclusive_min=True))
    else:
        max_storage = None
    permit = scaffold_entity(db.permits, {
        "permit_type": ptype,
        "site_code": site_code,
        "max_storage_tons": max_storage,
        "setback_ft": setback,
        "issued_at": None,
        "expires_at": None,
        "status": "APPLICATION",
    })
    permit["_expires_at"] = None
    return success_object(public(permit), 201)


@bp.get("/agronomy/environmental-permits")
def list_permits():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.permits.values())
    for p in items:
        lazy_permit(p)
    if "permit_type" in request.args:
        items = [p for p in items if p["permit_type"] == request.args["permit_type"]]
    if "status" in request.args:
        items = [p for p in items if p["status"] == request.args["status"]]
    if "site_code" in request.args:
        items = [p for p in items if p["site_code"] == request.args["site_code"]]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/environmental-permits/<permitId>")
def get_permit(permitId):
    require_roles(*ALL_ROLES)
    permit = _get_permit(permitId)
    lazy_permit(permit)
    return success_object(public(permit))


@bp.post("/agronomy/environmental-permits/<permitId>/begin-inspection")
def begin_inspection(permitId):
    require_roles("ComplianceOfficer")
    permit = _get_permit(permitId)
    if permit["status"] != "APPLICATION":
        raise invalid_transition("Permit not APPLICATION")
    permit["status"] = "UNDER_INSPECTION"
    touch(permit)
    return success_object(public(permit))


@bp.post("/agronomy/environmental-permits/<permitId>/activate")
def activate_permit(permitId):
    require_roles("ComplianceOfficer")
    permit = _get_permit(permitId)
    body = get_body()
    reject_unknown(body, {"expires_at"})
    expires = parse_instant(require(body, "expires_at"), "expires_at")
    if permit["status"] not in ("UNDER_INSPECTION", "RENEWAL"):
        raise invalid_transition("Permit not UNDER_INSPECTION or RENEWAL")
    if expires <= db.CLOCK.now():
        raise validation("expires_at must be later than the current clock instant")
    permit["status"] = "ACTIVE"
    permit["issued_at"] = now_stamp_helper()
    permit["expires_at"] = iso8601_ms(expires)
    permit["_expires_at"] = expires
    touch(permit)
    return success_object(public(permit))


@bp.post("/agronomy/environmental-permits/<permitId>/renew")
def renew_permit(permitId):
    require_roles("ComplianceOfficer")
    permit = _get_permit(permitId)
    lazy_permit(permit)
    if permit["status"] != "EXPIRED":
        raise invalid_transition("Permit not EXPIRED")
    permit["status"] = "RENEWAL"
    touch(permit)
    return success_object(public(permit))


@bp.post("/agronomy/environmental-permits/<permitId>/revoke")
def revoke_permit(permitId):
    require_roles("ComplianceOfficer")
    permit = _get_permit(permitId)
    body = get_body()
    reject_unknown(body, {"reason"})
    if permit["status"] != "ACTIVE":
        raise invalid_transition("Permit not ACTIVE")
    permit["status"] = "REVOKED"
    touch(permit)

    # Cascade hop 1: blenders on this site go OUT_OF_SERVICE
    affected_blenders = [b for b in db.blenders.values()
                         if b["site_code"] == permit["site_code"] and b["status"] == "ACTIVE"]
    affected_blender_ids = set()
    for b in affected_blenders:
        b["status"] = "OUT_OF_SERVICE"
        touch(b)
        affected_blender_ids.add(b["id"])

    # Cascade hop 2: SCHEDULED batches on those blenders -> VOIDED
    voided_batches = [b for b in db.blend_batches.values()
                      if b["blender_id"] in affected_blender_ids and b["status"] == "SCHEDULED"]
    voided_order_ids = set()
    for b in voided_batches:
        b["status"] = "VOIDED"
        b["void_reason"] = "PERMIT_REVOKED"
        touch(b)
        voided_order_ids.add(b["blend_order_id"])

    # Cascade hop 3: orders back to BOOKED
    for oid in voided_order_ids:
        order = db.blend_orders.get(oid)
        if order is not None and order["fulfillment_status"] == "SCHEDULED":
            order["fulfillment_status"] = "BOOKED"
            touch(order)

    return success_object(public(permit))
