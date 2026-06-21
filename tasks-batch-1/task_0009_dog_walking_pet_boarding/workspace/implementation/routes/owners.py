"""Owner routes."""
from __future__ import annotations

from flask import Blueprint

import db
import response
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_auth
from services.common import (
    get_json_body,
    new_common_fields,
    paginate,
    parse_pagination,
    require_str,
    sorted_by_created_at,
    strip_internal,
)
from services.lookup import get_owner_or_404

bp = Blueprint("owners", __name__)


def _owner_to_dict(o: dict) -> dict:
    return {
        "id": o["id"],
        "email": o["email"],
        "full_name": o["full_name"],
        "phone": o["phone"],
        "wallet_credit_cents": o["wallet_credit_cents"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


@bp.post("/api/v1/owners/register")
@require_auth(roles=["Anonymous", "Owner", "Sitter", "PlatformAdmin", "ClaimsAdjuster"])
def register_owner():
    body = get_json_body()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    phone = require_str(body, "phone")

    # Uniqueness on email
    for o in db.owners.values():
        if o["email"] == email:
            raise ApiError(ERR_INVALID_REQUEST, "email already in use.")

    with db.lock:
        owner = {
            **new_common_fields(),
            "email": email,
            "full_name": full_name,
            "phone": phone,
            "wallet_credit_cents": 0,
        }
        db.owners[owner["id"]] = owner
    return response.ok(_owner_to_dict(owner), status=201)


@bp.get("/api/v1/owners/<oid>")
@require_auth(roles=["Owner", "PlatformAdmin", "ClaimsAdjuster"])
def get_owner(oid: str):
    o = get_owner_or_404(oid)
    return response.ok(_owner_to_dict(o))


@bp.get("/api/v1/owners")
@require_auth(roles=["PlatformAdmin"])
def list_owners():
    limit, offset = parse_pagination()
    items = sorted_by_created_at(list(db.owners.values()))
    page, total = paginate(items, limit, offset)
    return response.list_ok([_owner_to_dict(o) for o in page], limit, offset, total)
