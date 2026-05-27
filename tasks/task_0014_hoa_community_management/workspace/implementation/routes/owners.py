"""Owner endpoints."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import ERR_DUPLICATE_OWNER_EMAIL, raise_err
from middleware import auth_required
from response import list_success, success
from .helpers import (
    fetch_or_404,
    get_json_body,
    paginate,
    parse_pagination,
    require_str,
)


bp = Blueprint("owners", __name__)


def _is_eligible_voter(owner: dict) -> bool:
    """Owner owns at least one Property in this community AND none of those
    properties has a FILED Lien."""
    owned = [p for p in db.properties.values()
             if p["owner_id"] == owner["id"]
             and p["community_id"] == owner["community_id"]]
    if not owned:
        return False
    for prop in owned:
        for lien in db.liens.values():
            if lien["property_id"] == prop["id"] and lien["status"] == "FILED":
                return False
    return True


def _serialize(o: dict) -> dict:
    return {
        "id": o["id"],
        "community_id": o["community_id"],
        "email": o["email"],
        "full_name": o["full_name"],
        "is_eligible_voter": _is_eligible_voter(o),
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


@bp.route("/hoa/owners", methods=["POST"])
@auth_required({"PlatformAdmin"})
def create_owner():
    body = get_json_body()
    community_id = require_str(body, "community_id")
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")

    fetch_or_404(db.communities, community_id, "Community")

    # Uniqueness within community (priority 17)
    for existing in db.owners.values():
        if existing["community_id"] == community_id and existing["email"] == email:
            raise_err(ERR_DUPLICATE_OWNER_EMAIL,
                      f"Owner email already used: {email}")

    record = {
        **db.make_common_fields(),
        "community_id": community_id,
        "email": email,
        "full_name": full_name,
        "status": "ACTIVE",
    }
    db.owners[record["id"]] = record
    return success(_serialize(record), status=201)


@bp.route("/hoa/owners/<oid>", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "Treasurer", "ACCMember", "HomeOwner"})
def fetch_owner(oid):
    o = fetch_or_404(db.owners, oid, "Owner")
    return success(_serialize(o))


@bp.route("/hoa/owners", methods=["GET"])
@auth_required({"PlatformAdmin", "BoardPresident", "BoardSecretary",
                "Treasurer", "ACCMember"})
def list_owners():
    limit, offset = parse_pagination()
    community_id = request.args.get("community_id")
    rows = list(db.owners.values())
    if community_id is not None:
        rows = [r for r in rows if r["community_id"] == community_id]
    page, total = paginate(rows, limit, offset)
    return list_success([_serialize(r) for r in page], total, limit, offset)
