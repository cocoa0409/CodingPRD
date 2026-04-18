from flask import Blueprint, request

from errors import (
    raise_error, ERR_NOT_FOUND, ERR_REFERENCED_ENTITY_MISSING,
    ERR_INVALID_RESERVATION_STATE,
)
from response import success
from middleware import require_roles
from util import add_common_fields, bump, check_version
from db import db
from services.tenant_service import refresh_tenant

bp = Blueprint("access_badges", __name__)


def badge_view(b: dict) -> dict:
    return {
        "id": b["id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
        "member_id": b["member_id"],
        "badge_serial": b["badge_serial"],
        "status": b["status"],
        "last_used_at": b.get("last_used_at"),
        "scheduled_suspend_on": b.get("scheduled_suspend_on"),
    }


@bp.route("/access-badges", methods=["POST"])
def issue_badge():
    require_roles("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    member_id = body.get("member_id")
    serial = body.get("badge_serial")
    if not member_id or not serial:
        raise_error(("ERR_INVALID_INPUT", 422), "member_id and badge_serial required")
    m = db.members.get(member_id)
    if not m:
        raise_error(ERR_REFERENCED_ENTITY_MISSING, "Member not found")
    if db.badge_by_serial(serial):
        raise_error(("ERR_INVALID_INPUT", 422), "Badge serial already exists")

    badge = {
        "member_id": member_id,
        "badge_serial": serial,
        "status": "ACTIVE",
        "last_used_at": None,
        "scheduled_suspend_on": None,
    }
    add_common_fields(badge, db.now(), db.new_id())
    db.access_badges[badge["id"]] = badge
    return success(badge_view(badge), 201)


@bp.route("/access-badges/<badge_id>/suspend", methods=["POST"])
def suspend_badge(badge_id):
    require_roles("PlatformAdmin")
    b = db.access_badges.get(badge_id)
    if not b:
        raise_error(ERR_NOT_FOUND, "Badge not found")
    body = request.get_json(silent=True) or {}
    check_version(b, body.get("version"))
    if b["status"] != "ACTIVE":
        raise_error(ERR_INVALID_RESERVATION_STATE, "Only ACTIVE badge can be suspended")
    b["status"] = "SUSPENDED"
    bump(b, db.now())
    return success(badge_view(b))


@bp.route("/access-badges/<badge_id>/reactivate", methods=["POST"])
def reactivate_badge(badge_id):
    require_roles("PlatformAdmin")
    b = db.access_badges.get(badge_id)
    if not b:
        raise_error(ERR_NOT_FOUND, "Badge not found")
    body = request.get_json(silent=True) or {}
    check_version(b, body.get("version"))
    if b["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_RESERVATION_STATE, "Only SUSPENDED badge can be reactivated")
    member = db.members.get(b["member_id"])
    if not member or member["status"] != "ACTIVE":
        raise_error(ERR_INVALID_RESERVATION_STATE, "Member not ACTIVE")
    tenant = db.tenants.get(member["tenant_id"])
    if tenant:
        refresh_tenant(tenant)
        if tenant["access_posture"] == "FROZEN":
            raise_error(ERR_INVALID_RESERVATION_STATE, "Tenant posture is FROZEN")
    b["status"] = "ACTIVE"
    bump(b, db.now())
    return success(badge_view(b))


@bp.route("/access-badges/<badge_id>/revoke", methods=["POST"])
def revoke_badge(badge_id):
    require_roles("PlatformAdmin")
    b = db.access_badges.get(badge_id)
    if not b:
        raise_error(ERR_NOT_FOUND, "Badge not found")
    body = request.get_json(silent=True) or {}
    check_version(b, body.get("version"))
    if b["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_error(ERR_INVALID_RESERVATION_STATE, "Only ACTIVE/SUSPENDED badge can be revoked")
    b["status"] = "REVOKED"
    bump(b, db.now())
    return success(badge_view(b))
