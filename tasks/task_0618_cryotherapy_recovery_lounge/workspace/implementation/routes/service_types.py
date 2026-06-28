"""Service-type (menu) endpoints (PRD §3.1)."""

from flask import Blueprint, request

import errors
from db import db
from helpers import (
    get_body, require_str, require_enum, require_int_min, opt_bool,
    parse_pagination, sort_by_created, paginate, stamp_new, opt_str,
)
from middleware import require_roles
from response import success, list_success
from serializers import serialize_service_type
from services.lookups import get_service_type_or_404

bp = Blueprint("service_types", __name__)

SERVICE_CODES = {"WHOLE_BODY_CRYO", "RED_LIGHT", "COMPRESSION", "INFRARED_SAUNA"}


@bp.post("/service-types")
@require_roles("PlatformAdmin")
def create_service_type():
    body = get_body()
    code = require_enum(body, "code", SERVICE_CODES)
    name = require_str(body, "name")
    duration_minutes = require_int_min(body, "duration_minutes", 5)
    buffer_minutes = require_int_min(body, "buffer_minutes", 0)
    credit_cost = require_int_min(body, "credit_cost", 1)
    requires_medical_clearance = opt_bool(body, "requires_medical_clearance", False)
    active = opt_bool(body, "active", True)
    # code is unique across the menu (scaffold §1.1).
    for st in db.service_types.values():
        if st["code"] == code:
            raise errors.invalid_request("Service code must be unique: " + code)
    st = stamp_new({
        "code": code,
        "name": name,
        "duration_minutes": duration_minutes,
        "buffer_minutes": buffer_minutes,
        "credit_cost": credit_cost,
        "requires_medical_clearance": requires_medical_clearance,
        "active": active,
    })
    db.service_types[st["id"]] = st
    return success(serialize_service_type(st), 201)


@bp.get("/service-types")
@require_roles("PlatformAdmin", "LocationManager", "Member", "Technician")
def list_service_types():
    limit, offset = parse_pagination()
    active = request.args.get("active")
    items = list(db.service_types.values())
    if active is not None:
        want = active.lower() == "true"
        items = [s for s in items if s["active"] == want]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_service_type(s) for s in page], limit, offset, total)


@bp.get("/service-types/<service_type_id>")
@require_roles("PlatformAdmin", "LocationManager", "Member", "Technician")
def get_service_type(service_type_id):
    st = get_service_type_or_404(service_type_id)
    return success(serialize_service_type(st), 200)
