"""Parent + ParentChildLink routes."""

from flask import Blueprint, g, request

from clock import clock
from config import DISPLAY_NAME_MAX, DISPLAY_NAME_MIN, MAX_CHILDREN_PER_PARENT
from db import db, init_common_fields
from errors import APIError
from middleware import require_auth
from response import empty_response, list_response, success_response
from services.pagination import get_pagination, slice_items
from services.sessions import cascade_cancel_for_child_link_revoke
from services.validators import (
    require_body,
    require_email,
    require_string,
)

parent_bp = Blueprint("parent", __name__)


@parent_bp.route("/parents", methods=["POST"])
@require_auth({"Parent", "PlatformAdmin"})
def create_parent():
    body = request.get_json(silent=True) or {}
    require_body(body)
    display_name = require_string(body, "display_name", DISPLAY_NAME_MIN, DISPLAY_NAME_MAX)
    email = require_email(body, "email")
    if email in db.parent_emails:
        raise APIError("ERR_VALIDATION", "Email already in use.")
    parent = init_common_fields({
        "display_name": display_name,
        "email": email,
        "managed_child_count": 0,
    })
    db.parents[parent["id"]] = parent
    db.parent_emails.add(email)
    return success_response(parent, status=201)


@parent_bp.route("/parents/<parent_id>", methods=["GET"])
@require_auth({"Parent", "PlatformAdmin"})
def get_parent(parent_id):
    parent = db.parents.get(parent_id)
    if parent is None:
        raise APIError("ERR_NOT_FOUND")
    if g.user_role == "Parent" and g.user_id != parent_id:
        raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
    return success_response(parent, status=200)


@parent_bp.route("/parents/<parent_id>/links", methods=["GET"])
@require_auth({"Parent", "PlatformAdmin"})
def list_links(parent_id):
    parent = db.parents.get(parent_id)
    if parent is None:
        raise APIError("ERR_NOT_FOUND")
    if g.user_role == "Parent" and g.user_id != parent_id:
        raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
    limit, offset = get_pagination()
    status_filter = request.args.get("link_status")
    items = [l for l in db.parent_child_links.values() if l["parent_id"] == parent_id]
    if status_filter:
        items = [l for l in items if l["link_status"] == status_filter]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = slice_items(items, limit, offset)
    return list_response(page, total, limit, offset, status=200)


@parent_bp.route("/parents/<parent_id>/links/<link_id>/approve", methods=["POST"])
@require_auth({"Parent"})
def approve_link(parent_id, link_id):
    parent = db.parents.get(parent_id)
    if parent is None:
        raise APIError("ERR_NOT_FOUND")
    link = db.parent_child_links.get(link_id)
    if link is None or link["parent_id"] != parent_id:
        raise APIError("ERR_NOT_FOUND")
    if g.user_id != parent_id:
        raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
    if link["link_status"] != "PENDING_PARENT_APPROVAL":
        raise APIError("ERR_INVALID_STATE")
    # Check child is MINOR
    student = db.students.get(link["student_id"])
    if student is None or student["account_type"] != "MINOR":
        raise APIError("ERR_INVALID_STATE")
    # Capacity check
    if parent["managed_child_count"] + 1 > MAX_CHILDREN_PER_PARENT:
        raise APIError("ERR_CHILD_LIMIT_EXCEEDED")
    link["link_status"] = "ACTIVE"
    link["approved_at"] = clock.now_iso()
    parent["managed_child_count"] += 1
    from db import touch
    touch(parent)
    return success_response(link, status=200)


@parent_bp.route("/parents/<parent_id>/links/<link_id>", methods=["DELETE"])
@require_auth({"Parent", "PlatformAdmin"})
def revoke_link(parent_id, link_id):
    parent = db.parents.get(parent_id)
    if parent is None:
        raise APIError("ERR_NOT_FOUND")
    link = db.parent_child_links.get(link_id)
    if link is None or link["parent_id"] != parent_id:
        raise APIError("ERR_NOT_FOUND")
    if g.user_role == "Parent" and g.user_id != parent_id:
        raise APIError("ERR_NOT_AUTHORIZED_FOR_RESOURCE")
    if link["link_status"] != "ACTIVE":
        raise APIError("ERR_INVALID_STATE")
    link["link_status"] = "REVOKED"
    if parent["managed_child_count"] > 0:
        parent["managed_child_count"] -= 1
    from db import touch
    touch(parent)
    cascade_cancel_for_child_link_revoke(link["student_id"])
    return empty_response(status=204)
