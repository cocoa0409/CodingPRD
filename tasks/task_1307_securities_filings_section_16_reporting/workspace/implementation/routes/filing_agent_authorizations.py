"""FilingAgentAuthorization CRUD + revoke."""
from flask import Blueprint, request

from db import db
from errors import (
    ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_AUTHORIZATION_INVALID_STATE, ApiError,
)
from middleware import require_role, get_auth
from response import success_object, success_list
from utils import (
    AUTHORIZATION_FIELDS, serialize, stamp_created, bump_version,
    parse_pagination, paginate,
)

auth_bp = Blueprint("filing_agent_authorizations", __name__)


def _get_auth_or_404(aid):
    a = db.filing_agent_authorizations.get(aid)
    if not a:
        raise ApiError(ERR_NOT_FOUND, f"FilingAgentAuthorization {aid} not found.", 404)
    return a


@auth_bp.route("/filing-agent-authorizations", methods=["POST"])
def create_authorization():
    user_id, role = require_role("ComplianceOfficer")
    body = request.get_json(force=True) or {}

    for f in ["issuer_id", "agent_user_id"]:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"{f} is required.", 400)

    if body["issuer_id"] not in db.issuers:
        raise ApiError(ERR_INVALID_REQUEST, f"issuer_id {body['issuer_id']} not found.", 400)

    auth = {
        "issuer_id": body["issuer_id"],
        "agent_user_id": body["agent_user_id"],
        "status": "ACTIVE",
    }
    stamp_created(auth)
    db.filing_agent_authorizations[auth["id"]] = auth
    return success_object(serialize(auth, AUTHORIZATION_FIELDS), 201)


@auth_bp.route("/filing-agent-authorizations", methods=["GET"])
def list_authorizations():
    get_auth()
    limit, offset = parse_pagination(request.args)
    items = sorted(db.filing_agent_authorizations.values(), key=lambda x: x["created_at"])
    for param in ["issuer_id", "status"]:
        val = request.args.get(param)
        if val:
            items = [a for a in items if str(a.get(param)) == val]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(a, AUTHORIZATION_FIELDS) for a in page], limit, offset, total)


@auth_bp.route("/filing-agent-authorizations/<authorizationId>", methods=["GET"])
def get_authorization(authorizationId):
    get_auth()
    a = _get_auth_or_404(authorizationId)
    return success_object(serialize(a, AUTHORIZATION_FIELDS))


@auth_bp.route("/filing-agent-authorizations/<authorizationId>/revoke", methods=["POST"])
def revoke_authorization(authorizationId):
    user_id, role = require_role("ComplianceOfficer")
    a = _get_auth_or_404(authorizationId)
    if a["status"] != "ACTIVE":
        raise ApiError(ERR_AUTHORIZATION_INVALID_STATE, "Revoke requires ACTIVE.", 409)
    a["status"] = "REVOKED"
    bump_version(a)
    return success_object(serialize(a, AUTHORIZATION_FIELDS))
