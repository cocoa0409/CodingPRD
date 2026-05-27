"""Property endpoints."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import ERR_DUPLICATE_UNIT_LABEL, raise_err
from middleware import auth_required
from response import list_success, success
from .helpers import (
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_str,
)


bp = Blueprint("properties", __name__)


def _serialize(p: dict) -> dict:
    return {
        "id": p["id"],
        "community_id": p["community_id"],
        "owner_id": p["owner_id"],
        "unit_label": p["unit_label"],
        "account_balance_cents": int(p.get("account_balance_cents", 0)),
        "compliance_posture": p.get("compliance_posture", "COMPLIANT"),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.route("/hoa/properties", methods=["POST"])
@auth_required({"PlatformAdmin"})
def create_property():
    body = get_json_body()
    community_id = require_str(body, "community_id")
    owner_id = require_str(body, "owner_id")
    unit_label = require_str(body, "unit_label")

    fetch_or_404(db.communities, community_id, "Community")
    owner = fetch_or_404(db.owners, owner_id, "Owner")

    # Owner must belong to the same community
    if owner["community_id"] != community_id:
        # Treated as a referential mismatch — surface as not found per
        # the spirit of body-FK existence checks.
        raise_err("ERR_NOT_FOUND",
                  "Owner not found in this community")

    # Uniqueness of unit_label within community (priority 18)
    for existing in db.properties.values():
        if (existing["community_id"] == community_id
                and existing["unit_label"] == unit_label):
            raise_err(ERR_DUPLICATE_UNIT_LABEL,
                      f"Unit label already used: {unit_label}")

    record = {
        **db.make_common_fields(),
        "community_id": community_id,
        "owner_id": owner_id,
        "unit_label": unit_label,
        "account_balance_cents": 0,
        "compliance_posture": "COMPLIANT",
    }
    db.properties[record["id"]] = record
    return success(_serialize(record), status=201)


@bp.route("/hoa/properties/<pid>", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "Treasurer", "ACCMember", "HomeOwner"})
def fetch_property(pid):
    p = fetch_or_404(db.properties, pid, "Property")
    return success(_serialize(p))


@bp.route("/hoa/properties", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "Treasurer", "ACCMember"})
def list_properties():
    limit, offset = parse_pagination()
    community_id = request.args.get("community_id")
    owner_id = request.args.get("owner_id")
    rows = list(db.properties.values())
    if community_id is not None:
        rows = [r for r in rows if r["community_id"] == community_id]
    if owner_id is not None:
        rows = [r for r in rows if r["owner_id"] == owner_id]
    page, total = paginate(rows, limit, offset)
    return list_success([_serialize(r) for r in page], total, limit, offset)
