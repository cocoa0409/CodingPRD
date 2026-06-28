"""Waiver endpoints (PRD §3.3)."""

from flask import Blueprint, request, g

import errors
from db import db, now_ts
from helpers import (
    get_body, require_object, require_bool, parse_pagination, sort_by_created,
    paginate, stamp_new, touch,
)
from middleware import require_roles
from response import success, list_success
from serializers import serialize_waiver
from services.lookups import (
    get_member_or_404, get_waiver_or_404, require_member_ownership,
)

bp = Blueprint("waivers", __name__)


def _active_waiver_for(member_id):
    for w in db.waivers.values():
        if w["member_id"] == member_id and w["status"] == "ACTIVE":
            return w
    return None


@bp.post("/members/<member_id>/waivers")
@require_roles("Member", "LocationManager")
def sign_waiver(member_id):
    member = get_member_or_404(member_id)
    require_member_ownership(member_id)
    body = get_body()
    screening_answers = require_object(body, "screening_answers")
    has_contraindication = require_bool(body, "has_contraindication")
    # Supersede any prior ACTIVE waiver in the same request (PRD §3.3).
    prior = _active_waiver_for(member_id)
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
    waiver = stamp_new({
        "member_id": member_id,
        "screening_answers": screening_answers,
        "has_contraindication": has_contraindication,
        "signed_at": now_ts(),
        "status": "ACTIVE",
    })
    db.waivers[waiver["id"]] = waiver
    # Recompute contraindication_flag from the new active waiver (PRD §3.3).
    member["contraindication_flag"] = has_contraindication
    touch(member)
    return success(serialize_waiver(waiver), 201)


@bp.get("/waivers")
@require_roles("PlatformAdmin", "LocationManager", "Member")
def list_waivers():
    limit, offset = parse_pagination()
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    items = list(db.waivers.values())
    if g.user_role == "Member":
        items = [w for w in items if w["member_id"] == g.user_id]
    if member_id is not None:
        items = [w for w in items if w["member_id"] == member_id]
    if status is not None:
        items = [w for w in items if w["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return list_success([serialize_waiver(w) for w in page], limit, offset, total)


@bp.get("/waivers/<waiver_id>")
@require_roles("PlatformAdmin", "LocationManager", "Member")
def get_waiver(waiver_id):
    waiver = get_waiver_or_404(waiver_id)
    if g.user_role == "Member" and g.user_id != waiver["member_id"]:
        raise errors.forbidden("A member may act only on their own resources")
    return success(serialize_waiver(waiver), 200)


@bp.post("/members/<member_id>/waivers/<waiver_id>/revoke")
@require_roles("LocationManager")
def revoke_waiver(member_id, waiver_id):
    # Path existence left-to-right: member, then waiver.
    member = get_member_or_404(member_id)
    waiver = get_waiver_or_404(waiver_id)
    # Revocation is permitted only on the member's ACTIVE waiver (PRD §3.3).
    if waiver["member_id"] != member_id or waiver["status"] != "ACTIVE":
        raise errors.invalid_state("Waiver is not the member's ACTIVE waiver")
    waiver["status"] = "REVOKED"
    touch(waiver)
    member["contraindication_flag"] = True
    touch(member)
    return success(serialize_waiver(waiver), 200)
