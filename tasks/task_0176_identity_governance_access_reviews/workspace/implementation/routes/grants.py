"""Grant routes (PRD §3.5).

Grants are created only via the approval cascade or a direct admin grant
(see identities). This module exposes get/list and manual revoke.
"""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role
from response import object_response, array_response
from services.common import (
    serialize, parse_pagination, paginate, filter_enum_param,
)
from services import domain

bp = Blueprint("grants", __name__)

READ_ROLES = {"AccessManager", "AccessApprover", "CampaignAdmin", "Certifier"}
GRANT_LIFECYCLE = {"PROVISIONING", "ACTIVE", "REVOKED"}
GRANT_REVIEW = {"NOT_DUE", "UNDER_REVIEW", "CERTIFIED", "FLAGGED"}


@bp.route("/grants/<id>", methods=["GET"])
def get_grant(id):
    require_role(READ_ROLES)
    with db.LOCK:
        record = db.grants.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Grant not found")
        return object_response(serialize(record), 200)


@bp.route("/grants", methods=["GET"])
def list_grants():
    require_role(READ_ROLES)
    identity_id = request.args.get("identity_id")
    entitlement_id = request.args.get("entitlement_id")
    source_request_id = request.args.get("source_request_id")
    lifecycle = filter_enum_param(request.args, "lifecycle_status", GRANT_LIFECYCLE)
    review = filter_enum_param(request.args, "review_status", GRANT_REVIEW)
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.grants.values())
        if identity_id is not None:
            records = [g for g in records if g["identity_id"] == identity_id]
        if entitlement_id is not None:
            records = [g for g in records if g["entitlement_id"] == entitlement_id]
        if source_request_id is not None:
            records = [g for g in records if g["source_request_id"] == source_request_id]
        if lifecycle is not None:
            records = [g for g in records if g["lifecycle_status"] == lifecycle]
        if review is not None:
            records = [g for g in records if g["review_status"] == review]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/grants/<id>/revoke", methods=["POST"])
def revoke_grant_route(id):
    user_id, _ = require_role({"AccessManager"})
    with db.LOCK:
        grant = db.grants.get(id)
        if grant is None:
            raise err(errors.ERR_NOT_FOUND, "Grant not found")
        if grant["lifecycle_status"] != "ACTIVE":
            raise err(errors.ERR_INVALID_STATE, "Grant is not ACTIVE")
        identity = db.identities.get(grant["identity_id"])
        domain.revoke_grant(grant, identity, user_id)
        return object_response(serialize(grant), 200)
