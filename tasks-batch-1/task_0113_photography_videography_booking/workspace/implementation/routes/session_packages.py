"""Session package catalogue (PRD §3.1)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import APIError, ERR_NOT_FOUND
from middleware import require_auth, ROLE_CLIENT, ROLE_STUDIO_ADMIN
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_str, require_enum, require_int, require_number,
    optional_bool, serialize, serialize_list, parse_pagination, paginate,
    order_by_created_at,
)
from services.common import stamp_create

bp = Blueprint("session_packages", __name__)

SESSION_TYPES = {"PORTRAIT", "WEDDING", "EVENT", "COMMERCIAL", "PRODUCT"}
TIERS = {"BASIC", "STANDARD", "PREMIUM"}


@bp.post("/studio/session-packages")
def create_package():
    require_auth([ROLE_STUDIO_ADMIN])
    body = get_body()
    name = require_str(body, "name")
    session_type = require_enum(body, "session_type", SESSION_TYPES)
    tier = require_enum(body, "tier", TIERS)
    base_fee_cents = require_int(body, "base_fee_cents", gt=0)
    included_shoot_hours = require_number(body, "included_shoot_hours", gt=0)
    overage_hourly_rate_cents = require_int(body, "overage_hourly_rate_cents", min_value=0)
    included_edited_images = require_int(body, "included_edited_images", min_value=0)
    deposit_pct = require_number(body, "deposit_pct", gt=0, le=1)
    requires_model_release = optional_bool(body, "requires_model_release", False)
    active = optional_bool(body, "active", True)

    package = {
        "name": name,
        "session_type": session_type,
        "tier": tier,
        "base_fee_cents": base_fee_cents,
        "included_shoot_hours": included_shoot_hours,
        "overage_hourly_rate_cents": overage_hourly_rate_cents,
        "included_edited_images": included_edited_images,
        "deposit_pct": deposit_pct,
        "requires_model_release": requires_model_release,
        "active": active,
    }
    stamp_create(package)
    db.session_packages[package["id"]] = package
    return ok_object(serialize(package), 201)


@bp.get("/studio/session-packages/<id>")
def get_package(id):
    require_auth([ROLE_CLIENT, ROLE_STUDIO_ADMIN])
    p = db.session_packages.get(id)
    if p is None:
        raise APIError(ERR_NOT_FOUND, 404, "Session package not found")
    return ok_object(serialize(p), 200)


@bp.get("/studio/session-packages")
def list_packages():
    require_auth([ROLE_CLIENT, ROLE_STUDIO_ADMIN])
    limit, offset = parse_pagination()
    items = list(db.session_packages.values())

    session_type = request.args.get("session_type")
    if session_type is not None:
        items = [p for p in items if p["session_type"] == session_type]
    tier = request.args.get("tier")
    if tier is not None:
        items = [p for p in items if p["tier"] == tier]
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [p for p in items if p["active"] == want]

    items = order_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)
