"""Removal requests: decide approve/reject (PRD §3.8)."""
from flask import Blueprint, g, request

from auth import require_roles, ALL_ROLES
from envelope import object_response
from errors import ApiError, ERR_REMOVAL_INVALID_STATE
from helpers import get_removal, paginated
from store import store, touch

bp = Blueprint("removals", __name__)


@bp.get("/api/removal-requests/<remId>")
@require_roles(*ALL_ROLES)
def get_one(remId):
    return object_response(get_removal(remId))


@bp.get("/api/removal-requests")
@require_roles(*ALL_ROLES)
def list_removals():
    return paginated(list(store.removals.values()), {
        "request_id": request.args.get("request_id"),
        "created_by_resident_id": request.args.get("created_by_resident_id"),
        "status": request.args.get("status"),
    })


@bp.post("/api/removal-requests/<remId>/approve")
@require_roles("CityEngineer")
def approve(remId):
    rem = get_removal(remId)
    if rem["status"] != "PENDING_REVIEW":
        raise ApiError(409, ERR_REMOVAL_INVALID_STATE,
                       "Only a PENDING_REVIEW removal request can be decided")
    rem["status"] = "REMOVAL_GRANTED"
    rem["decided_by_user_id"] = g.user_id
    touch(rem)
    req = store.requests[rem["request_id"]]
    req["status"] = "REMOVED"
    touch(req)
    return object_response(rem)


@bp.post("/api/removal-requests/<remId>/reject")
@require_roles("CityEngineer")
def reject(remId):
    rem = get_removal(remId)
    if rem["status"] != "PENDING_REVIEW":
        raise ApiError(409, ERR_REMOVAL_INVALID_STATE,
                       "Only a PENDING_REVIEW removal request can be decided")
    rem["status"] = "REMOVAL_DENIED"
    rem["decided_by_user_id"] = g.user_id
    touch(rem)
    req = store.requests[rem["request_id"]]
    req["status"] = "EFFECTIVENESS_CERTIFIED"
    touch(req)
    return object_response(rem)
