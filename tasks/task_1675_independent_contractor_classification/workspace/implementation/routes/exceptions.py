"""ExceptionGrant endpoints."""

from flask import Blueprint, request
from db import store, new_id, parse_iso
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_RESOURCE_NOT_FOUND, ERR_INVALID_STATE,
    ERR_EXCEPTION_CAPACITY_REACHED,
)
from middleware import require_auth, ALL_ROLES
from response import success, paginate
from services.core import (
    stamp_new, touch, get_engagement_or_404, lazy_expire_grant,
    downgrade_standing_on_revoke,
)

bp = Blueprint("exceptions", __name__)


@bp.route("/api/engagements/<eid>/exceptions", methods=["POST"])
def grant_exception(eid):
    user_id, _ = require_auth(["ComplianceBoardMember"])
    body = request.get_json(silent=True) or {}
    justification = body.get("justification")
    expires_at = body.get("expires_at")
    if not justification or not isinstance(justification, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "justification is required")
    exp = parse_iso(expires_at)
    if exp is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "expires_at must be a valid ISO8601 instant")

    eng = get_engagement_or_404(eid)
    # state validity (rung 5) precedes fiscal capacity (rung 10): terminal
    # lockdown of REJECTED / TERMINATED / CONVERTED engagements (PRD §2.9).
    if eng["status"] in ("REJECTED", "TERMINATED", "CONVERTED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Engagement is in a terminal status")
    jur = store.jurisdictions[eng["jurisdiction_id"]]

    # capacity: ACTIVE grants across all engagements of the jurisdiction
    active_count = 0
    for g in store.exceptions.values():
        lazy_expire_grant(g)
        if g["status"] != "ACTIVE":
            continue
        g_eng = store.engagements.get(g["engagement_id"])
        if g_eng and g_eng["jurisdiction_id"] == jur["id"]:
            active_count += 1
    if active_count >= jur["max_active_exceptions"]:
        raise ApiError(ERR_EXCEPTION_CAPACITY_REACHED, 422,
                       "Jurisdiction exception capacity reached")

    grant = {
        "id": new_id(),
        "engagement_id": eid,
        "justification": justification,
        "expires_at": expires_at,
        "granted_by_user_id": user_id,
        "status": "ACTIVE",
    }
    stamp_new(grant)
    store.exceptions[grant["id"]] = grant
    return success(grant, status=201)


@bp.route("/api/engagements/<eid>/exceptions", methods=["GET"])
def list_exceptions(eid):
    require_auth(ALL_ROLES)
    get_engagement_or_404(eid)
    items = [g for g in store.exceptions.values() if g["engagement_id"] == eid]
    for g in items:
        lazy_expire_grant(g)
    items.sort(key=lambda g: g["created_at"])
    page, pg = paginate(items, request.args)
    return success(page, pagination=pg)


@bp.route("/api/exceptions/<gid>/revoke", methods=["POST"])
def revoke_exception(gid):
    require_auth(["ComplianceBoardMember"])
    grant = store.exceptions.get(gid)
    if grant is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND, 404, "Exception grant not found")
    lazy_expire_grant(grant)
    if grant["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409, "Grant is not ACTIVE")
    grant["status"] = "REVOKED"
    touch(grant)
    eng = store.engagements.get(grant["engagement_id"])
    if eng:
        downgrade_standing_on_revoke(eng["contractor_id"])
    return success(grant)
