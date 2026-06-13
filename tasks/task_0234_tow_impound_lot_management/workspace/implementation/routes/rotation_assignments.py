"""RotationAssignment endpoints (get, list, accept, decline, expire, cancel)."""
from flask import Blueprint, request

import db
from clock import now
from errors import ApiError
from middleware import require_role, require_user_context
from response import object_response
from services import providers as provider_svc
from services import rotation
from services.serialize import public
from validators import paginate_and_respond, sort_by_created

bp = Blueprint("rotation_assignments", __name__)


def get_assignment_or_404(aid):
    a = db.rotation_assignments.get(aid)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", "Rotation assignment not found")
    return a


@bp.route("/rotation-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator", "TowProvider"})
    a = get_assignment_or_404(aid)
    return object_response(public(a), 200)


@bp.route("/rotation-assignments", methods=["GET"])
def list_assignments():
    user_id, role = require_user_context()
    require_role(role, {"LotOperator", "TowProvider"})
    provider_id = request.args.get("provider_id")
    lot_id = request.args.get("lot_id")
    status = request.args.get("status")
    items = list(db.rotation_assignments.values())
    if provider_id is not None:
        items = [a for a in items if a["provider_id"] == provider_id]
    if lot_id is not None:
        items = [a for a in items if a["lot_id"] == lot_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sort_by_created(items)
    return paginate_and_respond([public(a) for a in items])


@bp.route("/rotation-assignments/<aid>/accept", methods=["POST"])
def accept(aid):
    user_id, role = require_user_context()
    require_role(role, {"TowProvider"})
    a = get_assignment_or_404(aid)
    # state check first (priority 6)
    if a["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", "Assignment is not OFFERED")
    # ownership: only the offered provider may accept (ERR_FORBIDDEN_FOR_ROLE)
    if user_id != a["provider_id"]:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", "Only the offered provider may accept")
    # offer-expiry (priority 10)
    if now() > a["_expires_dt"]:
        raise ApiError("ERR_OFFER_EXPIRED", "Offer has expired")
    provider = db.tow_providers.get(a["provider_id"])
    if provider is None or provider["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_ACTIVE", "Provider is not ACTIVE")
    a["status"] = "ACCEPTED"
    db.touch(a)
    provider["offers_accepted_count"] += 1
    provider_svc.recompute_standing(provider)
    db.touch(provider)
    return object_response(public(a), 200)


@bp.route("/rotation-assignments/<aid>/decline", methods=["POST"])
def decline(aid):
    user_id, role = require_user_context()
    require_role(role, {"TowProvider"})
    a = get_assignment_or_404(aid)
    if a["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", "Assignment is not OFFERED")
    if user_id != a["provider_id"]:
        raise ApiError("ERR_FORBIDDEN_FOR_ROLE", "Only the offered provider may decline")
    a["status"] = "DECLINED"
    db.touch(a)
    rotation.reoffer_cascade(a)
    return object_response(public(a), 200)


@bp.route("/rotation-assignments/<aid>/expire", methods=["POST"])
def expire(aid):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    a = get_assignment_or_404(aid)
    if a["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", "Assignment is not OFFERED")
    if not (now() > a["_expires_dt"]):
        raise ApiError("ERR_OFFER_NOT_EXPIRED", "Offer has not yet expired")
    a["status"] = "EXPIRED"
    db.touch(a)
    rotation.reoffer_cascade(a)
    return object_response(public(a), 200)


@bp.route("/rotation-assignments/<aid>/cancel", methods=["POST"])
def cancel(aid):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    a = get_assignment_or_404(aid)
    if a["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", "Assignment is not OFFERED")
    a["status"] = "CANCELLED"
    db.touch(a)
    return object_response(public(a), 200)
