"""Access badge routes."""
from flask import Blueprint

from common import stamp_new, stamp_update, get_json_body, check_version
from db import db
from errors import api_error
from middleware import require_roles
from response import success

bp = Blueprint("badges", __name__)


@bp.route("/access-badges", methods=["POST"])
def create_badge():
    require_roles(["PlatformAdmin"])
    body = get_json_body()
    member_id = body.get("member_id")
    serial = body.get("badge_serial")

    member = db.members.get(member_id) if member_id else None
    if not member:
        raise api_error("ERR_REFERENCED_ENTITY_MISSING", "member not found")
    if not serial:
        raise api_error("ERR_INVALID_TIME_WINDOW", "badge_serial required")
    for b in db.badges.values():
        if b["badge_serial"] == serial:
            raise api_error("ERR_INVALID_TIME_WINDOW", "badge_serial already exists")

    badge = {
        "member_id": member_id,
        "badge_serial": serial,
        "status": "ACTIVE",
        "last_used_at": None,
    }
    stamp_new(badge)
    db.badges[badge["id"]] = badge
    return success(badge, status=201)


@bp.route("/access-badges/<badge_id>/suspend", methods=["POST"])
def suspend_badge(badge_id):
    require_roles(["PlatformAdmin"])
    badge = db.badges.get(badge_id)
    if not badge:
        raise api_error("ERR_NOT_FOUND", "badge not found")
    body = get_json_body()
    check_version(badge, body)
    if badge["status"] != "ACTIVE":
        raise api_error("ERR_INVALID_RESERVATION_STATE", "badge not ACTIVE")
    badge["status"] = "SUSPENDED"
    stamp_update(badge)
    return success(badge)


@bp.route("/access-badges/<badge_id>/reactivate", methods=["POST"])
def reactivate_badge(badge_id):
    require_roles(["PlatformAdmin"])
    badge = db.badges.get(badge_id)
    if not badge:
        raise api_error("ERR_NOT_FOUND", "badge not found")
    body = get_json_body()
    check_version(badge, body)
    if badge["status"] != "SUSPENDED":
        raise api_error("ERR_INVALID_RESERVATION_STATE", "badge not SUSPENDED")
    member = db.members.get(badge["member_id"])
    if not member or member["status"] != "ACTIVE":
        raise api_error("ERR_INVALID_RESERVATION_STATE", "member not ACTIVE")
    tenant = db.tenants.get(member["tenant_id"])
    if tenant and tenant.get("access_posture") == "FROZEN":
        raise api_error("ERR_ACCESS_POSTURE_DENIES", "tenant FROZEN")
    badge["status"] = "ACTIVE"
    stamp_update(badge)
    return success(badge)


@bp.route("/access-badges/<badge_id>/revoke", methods=["POST"])
def revoke_badge(badge_id):
    require_roles(["PlatformAdmin"])
    badge = db.badges.get(badge_id)
    if not badge:
        raise api_error("ERR_NOT_FOUND", "badge not found")
    body = get_json_body()
    check_version(badge, body)
    if badge["status"] not in ("ACTIVE", "SUSPENDED"):
        raise api_error("ERR_INVALID_RESERVATION_STATE", "badge not ACTIVE/SUSPENDED")
    badge["status"] = "REVOKED"
    stamp_update(badge)
    return success(badge)
