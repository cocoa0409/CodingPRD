"""Owner endpoints (PRD 3.1)."""

from flask import Blueprint

import db
import errors
from errors import raise_error
import middleware as mw
import response as resp
from helpers import new_entity, get_owner_or_404, check_claimant_owner_scope

bp = Blueprint("owners", __name__)


def owner_view(owner):
    return {
        "id": owner["id"],
        "full_name": owner["full_name"],
        "last_known_address": owner["last_known_address"],
        "state_code": owner["state_code"],
        "deceased_date": owner["deceased_date"],
        "created_at": owner["created_at"],
        "updated_at": owner["updated_at"],
        "version": owner["version"],
    }


@bp.post("/escheatment/owners")
def create_owner():
    ctx = mw.get_user()
    mw.require_role(ctx, ("ComplianceOfficer",))
    data = mw.body_json()
    full_name = mw.req_string(data, "full_name")
    address = mw.req_string(data, "last_known_address")
    state_code = mw.req_string(data, "state_code")
    deceased = None
    if "deceased_date" in data and data["deceased_date"] is not None:
        deceased = mw.parse_iso_date(data["deceased_date"], "deceased_date").isoformat()
    owner = new_entity({
        "full_name": full_name,
        "last_known_address": address,
        "state_code": state_code,
        "deceased_date": deceased,
    })
    db.owners[owner["id"]] = owner
    return resp.success(owner_view(owner), "object", 201)


@bp.get("/escheatment/owners")
def list_owners():
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    limit, offset = mw.pagination_params()
    items = list(db.owners.values())
    state_code = mw.request.args.get("state_code")
    if state_code is not None:
        items = [o for o in items if o["state_code"] == state_code]
    page, meta = mw.paginate(items, limit, offset)
    return resp.success([owner_view(o) for o in page], "array", 200, pagination=meta)


@bp.get("/escheatment/owners/<ownerId>")
def get_owner(ownerId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    owner = get_owner_or_404(ownerId)
    check_claimant_owner_scope(ctx, owner["id"])
    return resp.success(owner_view(owner), "object", 200)


@bp.get("/escheatment/owners/<ownerId>/properties")
def list_owner_properties(ownerId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    owner = get_owner_or_404(ownerId)
    check_claimant_owner_scope(ctx, owner["id"])
    limit, offset = mw.pagination_params()
    from routes_properties import property_view
    items = [p for p in db.properties.values() if p["owner_id"] == owner["id"]]
    page, meta = mw.paginate(items, limit, offset)
    return resp.success([property_view(p) for p in page], "array", 200, pagination=meta)


@bp.get("/escheatment/owners/<ownerId>/owner-claims")
def list_owner_claims(ownerId):
    ctx = mw.get_user()
    mw.require_role(ctx, ("Any",))
    owner = get_owner_or_404(ownerId)
    check_claimant_owner_scope(ctx, owner["id"])
    limit, offset = mw.pagination_params()
    from routes_claims import claim_view
    items = [c for c in db.claims.values() if c["claimant_owner_id"] == owner["id"]]
    page, meta = mw.paginate(items, limit, offset)
    return resp.success([claim_view(c) for c in page], "array", 200, pagination=meta)
