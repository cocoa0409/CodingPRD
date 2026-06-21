"""Segregation-of-duties policy routes (PRD §3.1).

Names a toxic entitlement pair; the two ids must differ (ERR_SOD_PAIR_INVALID).
severity HARD (default) | SOFT. status begins ACTIVE; only ACTIVE policies are
evaluated.
"""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import require_role, get_json_body
from response import object_response, array_response
from services.common import (
    serialize, require_string, require_enum,
    parse_pagination, paginate, filter_enum_param,
)

bp = Blueprint("sod_policies", __name__)

READ_ROLES = {"CatalogAdmin", "AccessManager", "AccessApprover"}
SEVERITY_VALUES = {"HARD", "SOFT"}
STATUS_VALUES = {"ACTIVE", "DISABLED"}


@bp.route("/sod-policies", methods=["POST"])
def create_sod_policy():
    require_role({"CatalogAdmin"})
    body = get_json_body()
    name = require_string(body, "name")
    entitlement_a_id = require_string(body, "entitlement_a_id")
    entitlement_b_id = require_string(body, "entitlement_b_id")
    severity = require_enum(body, "severity", SEVERITY_VALUES, default="HARD")

    with db.LOCK:
        # Body FK existence (ERR_NOT_FOUND) before the pair-equality rule.
        if db.entitlements.get(entitlement_a_id) is None:
            raise err(errors.ERR_NOT_FOUND, "entitlement_a_id not found")
        if db.entitlements.get(entitlement_b_id) is None:
            raise err(errors.ERR_NOT_FOUND, "entitlement_b_id not found")
        if entitlement_a_id == entitlement_b_id:
            raise err(errors.ERR_SOD_PAIR_INVALID,
                      "entitlement_a_id must differ from entitlement_b_id")

        common = db.new_common()
        record = {
            "id": common["id"],
            "created_at": common["created_at"],
            "updated_at": common["updated_at"],
            "version": common["version"],
            "_seq": common["_seq"],
            "name": name,
            "entitlement_a_id": entitlement_a_id,
            "entitlement_b_id": entitlement_b_id,
            "severity": severity,
            "status": "ACTIVE",
        }
        db.sod_policies[record["id"]] = record
        return object_response(serialize(record), 201)


@bp.route("/sod-policies/<id>", methods=["GET"])
def get_sod_policy(id):
    require_role(READ_ROLES)
    with db.LOCK:
        record = db.sod_policies.get(id)
        if record is None:
            raise err(errors.ERR_NOT_FOUND, "SoD policy not found")
        return object_response(serialize(record), 200)


@bp.route("/sod-policies", methods=["GET"])
def list_sod_policies():
    require_role(READ_ROLES)
    a_id = request.args.get("entitlement_a_id")
    b_id = request.args.get("entitlement_b_id")
    status = filter_enum_param(request.args, "status", STATUS_VALUES)
    limit, offset = parse_pagination(request.args)
    with db.LOCK:
        records = list(db.sod_policies.values())
        # Filter by either side of the pair (each filter matches that named side).
        if a_id is not None:
            records = [r for r in records if r["entitlement_a_id"] == a_id]
        if b_id is not None:
            records = [r for r in records if r["entitlement_b_id"] == b_id]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        items, total = paginate(records, limit, offset)
        return array_response(items, limit, offset, total, 200)
