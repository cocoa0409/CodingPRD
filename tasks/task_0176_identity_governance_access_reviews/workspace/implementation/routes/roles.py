"""Role routes (PRD §3.1).

A role bundles entitlements via entitlement_ids (membership list). At create
time every element must reference an existing ACTIVE entitlement.
requires_dual_approval is computed TRUE when the bundle holds >=1 privileged
entitlement. status ACTIVE->RETIRED via retire.
"""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, require_array,
    parse_pagination, paginate, filter_enum_param,
)

bp = Blueprint("roles", __name__)

ALL_ROLES = {"CatalogAdmin", "AccessManager", "AccessApprover", "CampaignAdmin", "Certifier"}
STATUS_VALUES = {"ACTIVE", "RETIRED"}


@bp.route("/roles", methods=["POST"])
def create_role():
    require_role({"CatalogAdmin"})
    body = get_json_body()
    name = require_string(body, "name")
    entitlement_ids = require_array(body, "entitlement_ids")
    for eid in entitlement_ids:
        if not isinstance(eid, str):
            raise err(errors.ERR_VALIDATION, "entitlement_ids must contain strings")

    with db.LOCK:
        # Body FK existence (ERR_NOT_FOUND), then ACTIVE check.
        for eid in entitlement_ids:
            ent = db.entitlements.get(eid)
            if ent is None:
                raise err(errors.ERR_NOT_FOUND, "Entitlement %s not found" % eid)
        for eid in entitlement_ids:
            ent = db.entitlements.get(eid)
            if ent["status"] != "ACTIVE":
                raise err(errors.ERR_ENTITLEMENT_ARCHIVED,
                          "Entitlement %s is not ACTIVE" % eid)

        requires_dual = any(
            db.entitlements[eid]["is_privileged"] for eid in entitlement_ids
        )
        common = db.new_common()
        record = {
            "id": common["id"],
            "created_at": common["created_at"],
            "updated_at": common["updated_at"],
            "version": common["version"],
            "_seq": common["_seq"],
            "name": name,
            "entitlement_ids": list(entitlement_ids),
            "requires_dual_approval": requires_dual,
            "status": "ACTIVE",
        }
        db.roles[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/roles/<id>", methods=["GET"])
def get_role(id):
    require_role(ALL_ROLES)
    with db.LOCK:
        record = db.roles.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Role not found")
        return object_response(serialize(record), 200)


@bp.route("/roles", methods=["GET"])
def list_roles():
    require_role(ALL_ROLES)
    status = filter_enum_param(request.args, "status", STATUS_VALUES)
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.roles.values())
        if status is not None:
            records = [r for r in records if r["status"] == status]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/roles/<id>/retire", methods=["POST"])
def retire_role(id):
    require_role({"CatalogAdmin"})
    with db.LOCK:
        record = db.roles.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Role not found")
        if record["status"] != "ACTIVE":
            raise err(errors.ERR_INVALID_STATE, "Role is not ACTIVE")
        record["status"] = "RETIRED"
        db.touch(record)
        return object_response(serialize(record), 200)
