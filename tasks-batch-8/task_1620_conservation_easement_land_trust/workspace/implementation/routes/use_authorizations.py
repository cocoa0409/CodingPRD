"""Discretionary use authorization endpoints."""
from flask import Blueprint, g, request

import db
import utils
from errors import ApiError
from middleware import ANY_ROLE, body, paginate, require_roles
from response import ok
from services import domain

bp = Blueprint("use_authorizations", __name__)


def get_use_auth_or_404(auth_id):
    r = db.use_authorizations.get(auth_id)
    if r is None:
        raise ApiError("ERR_USE_AUTHORIZATION_NOT_FOUND", "UseAuthorization id does not exist.", 404)
    return r


@bp.route("/stewardship/use-authorizations", methods=["POST"])
@require_roles("Landowner")
def create_use_auth():
    b = body()
    easement_id = b.get("easement_id")
    if easement_id is not None and easement_id not in db.easements:
        raise ApiError("ERR_EASEMENT_NOT_FOUND", "Easement id does not exist.", 404)
    e = db.easements.get(easement_id)
    if e is not None and e["status"] != "RECORDED":
        raise ApiError("ERR_EASEMENT_NOT_RECORDED", "Child operational create requires a RECORDED easement.", 409)
    use_type = b.get("use_type")
    # Uniqueness (priority 8): one active authorization per (easement, use_type).
    if isinstance(use_type, str) and any(
        a["easement_id"] == easement_id
        and a["use_type"] == use_type
        and a["status"] in domain.ACTIVE_USE_AUTH_STATES
        for a in db.use_authorizations.values()
    ):
        raise ApiError(
            "ERR_USE_CURRENTLY_AUTHORIZED",
            "An active authorization already covers this use type on this easement.",
            409,
        )
    justification = b.get("justification")
    if e is None or not isinstance(use_type, str) or not isinstance(justification, str):
        raise ApiError("ERR_INVALID_REQUEST", "easement_id, use_type and justification are required.", 400)
    if use_type not in e["permitted_use_matrix"]:
        raise ApiError("ERR_INVALID_REQUEST", "use_type must be a key of the permitted_use_matrix.", 400)
    if e["permitted_use_matrix"][use_type] != "DISCRETIONARY":
        raise ApiError(
            "ERR_USE_NOT_DISCRETIONARY",
            "Only a DISCRETIONARY matrix cell is authorizable.",
            422,
        )
    if g.user_id != e["current_landowner_id"]:
        raise ApiError("ERR_NOT_CURRENT_LANDOWNER", "Caller is not the easement's current landowner.", 403)
    now = utils.now_iso()
    r = {
        "id": utils.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "easement_id": easement_id,
        "use_type": use_type,
        "requested_by_landowner_id": g.user_id,
        "justification": justification,
        "decision": None,
        "conditions": None,
        "decision_reason": None,
        "conditions_breached": False,
        "status": "REQUESTED",
    }
    db.use_authorizations[r["id"]] = r
    return ok(domain.use_auth_json(r), 201)


@bp.route("/stewardship/use-authorizations", methods=["GET"])
@require_roles(*ANY_ROLE)
def list_use_auths():
    filters = {}
    for key in ("easement_id", "requested_by_landowner_id", "use_type", "status"):
        v = request.args.get(key)
        if v is not None:
            filters[key] = v
    return paginate(list(db.use_authorizations.values()), domain.use_auth_json, filters)


@bp.route("/stewardship/use-authorizations/<useAuthorizationId>", methods=["GET"])
@require_roles(*ANY_ROLE)
def get_use_auth(useAuthorizationId):
    return ok(domain.use_auth_json(get_use_auth_or_404(useAuthorizationId)))


@bp.route("/stewardship/use-authorizations/<useAuthorizationId>/decide", methods=["POST"])
@require_roles("StewardshipCoordinator")
def decide_use_auth(useAuthorizationId):
    r = get_use_auth_or_404(useAuthorizationId)
    if r["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_USE_AUTHORIZATION_STATE", "Decide requires REQUESTED.", 409)
    # Amendment freeze (PRD §3.5): an in-flight amendment touching this cell blocks decide.
    for a in db.amendment_requests.values():
        if (
            a["easement_id"] == r["easement_id"]
            and a["status"] in domain.IN_FLIGHT_AMENDMENT_STATES
            and any(ch["use_type"] == r["use_type"] for ch in a["requested_changes"])
        ):
            raise ApiError(
                "ERR_AMENDMENT_FREEZE_CONFLICT",
                "An in-flight amendment touches this use type.",
                409,
            )
    b = body()
    decision = b.get("decision")
    conditions = b.get("conditions")
    reason = b.get("decision_reason")
    if decision not in ("APPROVED", "APPROVED_WITH_CONDITIONS", "DENIED"):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "decision must be APPROVED | APPROVED_WITH_CONDITIONS | DENIED.",
            400,
        )
    if decision == "APPROVED_WITH_CONDITIONS" and (
        not isinstance(conditions, list) or len(conditions) == 0
    ):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "conditions must be a non-empty array when decision is APPROVED_WITH_CONDITIONS.",
            400,
        )
    if reason is not None and not isinstance(reason, str):
        raise ApiError("ERR_INVALID_REQUEST", "decision_reason must be a string.", 400)
    r["decision"] = decision
    r["status"] = decision
    r["conditions"] = conditions if decision == "APPROVED_WITH_CONDITIONS" else None
    r["decision_reason"] = reason
    domain.bump(r)
    return ok(domain.use_auth_json(r))
