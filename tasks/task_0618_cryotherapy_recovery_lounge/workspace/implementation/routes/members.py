"""Member endpoints (PRD §3.3)."""

from flask import Blueprint, request, g

import errors
from db import db
from helpers import (
    get_body, require_str, parse_pagination, sort_by_created, paginate, stamp_new,
)
from middleware import require_roles
from response import success, list_success
from serializers import serialize_member
from services.lookups import get_member_or_404, ref_location_or_404

bp = Blueprint("members", __name__)


@bp.post("/members")
@require_roles("PlatformAdmin", "LocationManager")
def create_member():
    body = get_body()
    home_location_id = require_str(body, "home_location_id")
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    state_code = require_str(body, "state_code")
    # Priority 4: body FK existence.
    ref_location_or_404(home_location_id)
    # email is unique (scaffold §1.1).
    for m in db.members.values():
        if m["email"] == email:
            raise errors.invalid_request("Member email must be unique: " + email)
    member = stamp_new({
        "home_location_id": home_location_id,
        "email": email,
        "full_name": full_name,
        "state_code": state_code,
        "contraindication_flag": False,
        "intro_offer_used": False,
        "credit_balance": 0,
        "status": "ACTIVE",
    })
    db.members[member["id"]] = member
    return success(serialize_member(member), 201)


@bp.get("/members")
@require_roles("PlatformAdmin", "LocationManager")
def list_members():
    limit, offset = parse_pagination()
    home_location_id = request.args.get("home_location_id")
    status = request.args.get("status")
    items = list(db.members.values())
    if home_location_id is not None:
        items = [m for m in items if m["home_location_id"] == home_location_id]
    if status is not None:
        items = [m for m in items if m["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_member(m) for m in page], limit, offset, total)


@bp.get("/members/<member_id>")
@require_roles("PlatformAdmin", "LocationManager", "Member")
def get_member(member_id):
    member = get_member_or_404(member_id)
    # A Member may read only their own member resource (PRD §2.1 ownership).
    if g.user_role == "Member" and g.user_id != member_id:
        raise errors.forbidden("A member may act only on their own resources")
    return success(serialize_member(member), 200)
