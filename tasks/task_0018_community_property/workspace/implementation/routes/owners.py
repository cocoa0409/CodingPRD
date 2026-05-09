"""Owner CRUD endpoints."""
from __future__ import annotations

from flask import Blueprint, g

import db
from errors import (
    APIError,
    ERR_FORBIDDEN,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
)
from middleware import require_roles
from response import success, success_list
from services.common import stamp_create
from services.voting_status import recompute_for_owner
from utils import get_body, paginate, parse_pagination, require_field

bp = Blueprint("owners", __name__)


@bp.post("/owners")
@require_roles("PropertyManager")
def create_owner():
    body = get_body()
    full_name = require_field(body, "full_name")
    id_card_no = require_field(body, "id_card_no")
    household_register_no = require_field(body, "household_register_no")
    phone = require_field(body, "phone")

    # PRD §3.1: id_card_no must be unique across the community.
    for existing in db.owners.values():
        if existing.get("id_card_no") == id_card_no:
            # PRD does not assign a dedicated error id for owner-id duplication;
            # use ERR_VALIDATION (422) which matches the generic uniqueness flavor.
            raise APIError(ERR_VALIDATION, "id_card_no already registered.", 422)

    owner = {
        "full_name": full_name,
        "id_card_no": id_card_no,
        "household_register_no": household_register_no,
        "phone": phone,
        "voting_status": "ELIGIBLE",
    }
    stamp_create(owner)
    db.owners[owner["id"]] = owner
    # Initial voting_status is ELIGIBLE per PRD; recompute will keep it ELIGIBLE
    # (no properties yet => INELIGIBLE_NO_PROPERTY isn't applied because PRD
    # explicitly states "starts with voting_status set to ELIGIBLE").
    return success(owner, status=201)


@bp.get("/owners")
@require_roles("PropertyManager", "CommitteeChair")
def list_owners():
    voting_status = (
        __import__("flask").request.args.get("voting_status")
    )
    items = list(db.owners.values())
    if voting_status:
        items = [o for o in items if o.get("voting_status") == voting_status]
    items.sort(key=lambda o: (o.get("created_at", ""), o.get("id", "")))
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.get("/owners/<oid>")
@require_roles("PropertyManager", "CommitteeChair", "Owner")
def get_owner(oid):
    owner = db.owners.get(oid)
    if owner is None:
        raise APIError(ERR_NOT_FOUND, f"Owner {oid} not found.", 404)
    if g.user_role == "Owner" and g.user_id != oid:
        raise APIError(ERR_FORBIDDEN, "Owners may only view themselves.", 403)
    return success(owner)
