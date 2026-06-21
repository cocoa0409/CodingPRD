"""EmergencyContact routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
import response
from errors import ApiError, ERR_PRIMARY_CONTACT_EXISTS
from middleware import require_auth
from services.common import (
    get_json_body,
    new_common_fields,
    paginate,
    parse_pagination,
    require_enum,
    require_int_range,
    require_str,
    sorted_by_created_at,
)
from services.lookup import fk_owner, get_emergency_contact_or_404

bp = Blueprint("emergency_contacts", __name__)


_RELATIONSHIPS = {"SPOUSE", "PARENT", "FRIEND", "VET", "NEIGHBOR", "OTHER"}


def ec_to_dict(e: dict) -> dict:
    return {
        "id": e["id"],
        "owner_id": e["owner_id"],
        "full_name": e["full_name"],
        "phone": e["phone"],
        "relationship": e["relationship"],
        "priority": e["priority"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


@bp.post("/api/v1/emergency-contacts")
@require_auth(roles=["Owner"])
def create_ec():
    body = get_json_body()
    owner_id = require_str(body, "owner_id")
    full_name = require_str(body, "full_name")
    phone = require_str(body, "phone")
    relationship = require_enum(body, "relationship", _RELATIONSHIPS)
    priority = require_int_range(body, "priority", low=1, high=3)

    fk_owner(owner_id)

    # Uniqueness: at most one priority=1 per Owner
    if priority == 1:
        for e in db.emergency_contacts.values():
            if e["owner_id"] == owner_id and e["priority"] == 1:
                raise ApiError(
                    ERR_PRIMARY_CONTACT_EXISTS,
                    "Owner already has a primary EmergencyContact.",
                )

    with db.lock:
        ec = {
            **new_common_fields(),
            "owner_id": owner_id,
            "full_name": full_name,
            "phone": phone,
            "relationship": relationship,
            "priority": priority,
        }
        db.emergency_contacts[ec["id"]] = ec
    return response.ok(ec_to_dict(ec), status=201)


@bp.get("/api/v1/emergency-contacts/<eid>")
@require_auth(roles=["Owner", "PlatformAdmin"])
def get_ec(eid: str):
    e = get_emergency_contact_or_404(eid)
    return response.ok(ec_to_dict(e))


@bp.get("/api/v1/emergency-contacts")
@require_auth(roles=["Owner", "PlatformAdmin"])
def list_ec():
    limit, offset = parse_pagination()
    owner_id = request.args.get("owner_id")

    items = list(db.emergency_contacts.values())
    if owner_id is not None:
        items = [e for e in items if e["owner_id"] == owner_id]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([ec_to_dict(e) for e in page], limit, offset, total)
