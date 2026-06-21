"""Entitlement routes (PRD §3.1).

An entitlement is the finest-grained provisioning unit. status ACTIVE->ARCHIVED
via archive. risk_weight integer 0..100 (default 10); is_privileged default
false (PRD §3.1).
"""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, optional_bool, optional_int,
    parse_pagination, paginate, filter_enum_param, filter_bool_param,
)

bp = Blueprint("entitlements", __name__)

ALL_ROLES = {"CatalogAdmin", "AccessManager", "AccessApprover", "CampaignAdmin", "Certifier"}
STATUS_VALUES = {"ACTIVE", "ARCHIVED"}


@bp.route("/entitlements", methods=["POST"])
def create_entitlement():
    require_role({"CatalogAdmin"})
    body = get_json_body()
    name = require_string(body, "name")
    system_code = require_string(body, "system_code")
    is_privileged = optional_bool(body, "is_privileged", False)
    risk_weight = optional_int(body, "risk_weight", 10, minimum=0, maximum=100)

    with db.LOCK:
        common = db.new_common()
        record = {
            "id": common["id"],
            "created_at": common["created_at"],
            "updated_at": common["updated_at"],
            "version": common["version"],
            "_seq": common["_seq"],
            "name": name,
            "system_code": system_code,
            "is_privileged": is_privileged,
            "risk_weight": risk_weight,
            "status": "ACTIVE",
        }
        db.entitlements[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/entitlements/<id>", methods=["GET"])
def get_entitlement(id):
    require_role(ALL_ROLES)
    with db.LOCK:
        record = db.entitlements.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Entitlement not found")
        return object_response(serialize(record), 200)


@bp.route("/entitlements", methods=["GET"])
def list_entitlements():
    require_role(ALL_ROLES)
    is_privileged = filter_bool_param(request.args, "is_privileged")
    status = filter_enum_param(request.args, "status", STATUS_VALUES)
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.entitlements.values())
        if is_privileged is not None:
            records = [r for r in records if r["is_privileged"] == is_privileged]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)


@bp.route("/entitlements/<id>/archive", methods=["POST"])
def archive_entitlement(id):
    require_role({"CatalogAdmin"})
    with db.LOCK:
        record = db.entitlements.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "Entitlement not found")
        if record["status"] != "ACTIVE":
            raise err(errors.ERR_INVALID_STATE, "Entitlement is not ACTIVE")
        record["status"] = "ARCHIVED"
        db.touch(record)
        return object_response(serialize(record), 200)
