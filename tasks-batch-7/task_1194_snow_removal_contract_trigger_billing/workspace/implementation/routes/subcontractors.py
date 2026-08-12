"""Subcontractor endpoints."""
from flask import Blueprint, request
import db
from middleware import require_roles, get_pagination, get_json_body
from response import success_object, success_created, success_list
from errors import *
from services.helpers import _touch

bp = Blueprint("subcontractors", __name__)

ALLOWED_CREATE_FIELDS = {"legal_name", "contact_email", "has_loader", "has_brine_truck"}


@bp.route("/subcontractors", methods=["POST"])
def create_subcontractor():
    user_id, role = require_roles("OpsDispatcher")
    body = get_json_body()
    unknown = set(body.keys()) - ALLOWED_CREATE_FIELDS
    if unknown:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown fields: {', '.join(unknown)}", 400)

    legal_name = body.get("legal_name")
    contact_email = body.get("contact_email")
    if not legal_name:
        raise ApiError(ERR_INVALID_REQUEST, "legal_name is required", 400)
    if not contact_email:
        raise ApiError(ERR_INVALID_REQUEST, "contact_email is required", 400)

    sub = {
        "id": db._new_id(),
        "legal_name": legal_name,
        "contact_email": contact_email,
        "has_loader": body.get("has_loader", False),
        "has_brine_truck": body.get("has_brine_truck", False),
        "status": "PENDING",
        "assignments_released_count": 0,
        "assignments_failed_count": 0,
        "active_assignment_count": 0,
        "reliability_score": 0,
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }
    db.subcontractors.create(sub)
    return success_created(sub)


def _get_sub_or_404(id):
    s = db.subcontractors.get(id)
    if not s:
        raise ApiError(ERR_NOT_FOUND, f"Subcontractor {id} not found", 404)
    return s


@bp.route("/subcontractors/<id>", methods=["GET"])
def get_subcontractor(id):
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher", "Subcontractor", "ClaimsAdjuster")
    sub = _get_sub_or_404(id)
    if role == "Subcontractor" and sub["id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, "Not your subcontractor record", 403)
    return success_object(sub)


@bp.route("/subcontractors", methods=["GET"])
def list_subcontractors():
    user_id, role = require_roles("PlatformAdmin", "OpsDispatcher")
    limit, offset = get_pagination()
    all_subs = db.subcontractors.list_all()
    status = request.args.get("status")
    if status:
        all_subs = [s for s in all_subs if s.get("status") == status]
    all_subs = sorted(all_subs, key=lambda s: s.get("created_at", ""))
    total = len(all_subs)
    page = all_subs[offset:offset + limit]
    return success_list(page, total, limit, offset)


@bp.route("/subcontractors/<id>/approve", methods=["POST"])
def approve_subcontractor(id):
    user_id, role = require_roles("PlatformAdmin")
    sub = _get_sub_or_404(id)
    if sub["status"] not in ("PENDING", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, f"Cannot approve from {sub['status']}", 409)
    sub["status"] = "APPROVED"
    _touch(sub)
    db.subcontractors.update(id, sub)
    return success_object(sub)


@bp.route("/subcontractors/<id>/suspend", methods=["POST"])
def suspend_subcontractor(id):
    user_id, role = require_roles("PlatformAdmin")
    sub = _get_sub_or_404(id)
    if sub["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, f"Cannot suspend from {sub['status']}", 409)
    sub["status"] = "SUSPENDED"
    _touch(sub)
    db.subcontractors.update(id, sub)
    return success_object(sub)
