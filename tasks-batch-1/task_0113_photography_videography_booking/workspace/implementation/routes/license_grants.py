"""License grants: usage/licensing rights (PRD §3.8)."""
from __future__ import annotations

from flask import Blueprint, g

import db
from errors import (
    APIError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER,
)
from middleware import require_auth, ROLE_CLIENT, ROLE_STUDIO_ADMIN
from response import ok_object, ok_array
from routes._helpers import (
    get_body, require_enum, require_int, serialize, serialize_list,
    parse_pagination, paginate, order_by_created_at,
)
from services import calculations as calc
from services.common import stamp_create, touch

bp = Blueprint("license_grants", __name__)

USAGE_SCOPES = {"PERSONAL", "COMMERCIAL", "EDITORIAL", "EXCLUSIVE"}
TERRITORIES = {"LOCAL", "NATIONAL", "WORLDWIDE"}


@bp.post("/studio/bookings/<id>/license-grants")
def create_grant(id):
    require_auth([ROLE_STUDIO_ADMIN])
    booking = db.bookings.get(id)
    if booking is None:
        raise APIError(ERR_NOT_FOUND, 404, "Booking not found")

    body = get_body()
    usage_scope = require_enum(body, "usage_scope", USAGE_SCOPES)
    territory = require_enum(body, "territory", TERRITORIES)
    term_months = require_int(body, "term_months", min_value=0)

    fee = calc.license_fee(usage_scope, territory, term_months)

    grant = {
        "booking_id": booking["id"],
        "usage_scope": usage_scope,
        "territory": territory,
        "term_months": term_months,
        "fee_cents": fee,
        "status": "ACTIVE",
    }
    stamp_create(grant)
    db.license_grants[grant["id"]] = grant
    return ok_object(serialize(grant), 201)


@bp.get("/studio/bookings/<id>/license-grants")
def list_grants_for_booking(id):
    require_auth([ROLE_CLIENT, ROLE_STUDIO_ADMIN])
    booking = db.bookings.get(id)
    if booking is None:
        raise APIError(ERR_NOT_FOUND, 404, "Booking not found")
    if g.user_role == ROLE_CLIENT and g.user_id != booking["client_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Caller does not own this booking")
    limit, offset = parse_pagination()
    items = [grant for grant in db.license_grants.values()
             if grant["booking_id"] == id]
    items = order_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.post("/studio/license-grants/<id>/revoke")
def revoke_grant(id):
    require_auth([ROLE_STUDIO_ADMIN])
    grant = db.license_grants.get(id)
    if grant is None:
        raise APIError(ERR_NOT_FOUND, 404, "License grant not found")
    if grant["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "Grant is not ACTIVE")
    grant["status"] = "REVOKED"
    touch(grant)
    return ok_object(serialize(grant), 200)
