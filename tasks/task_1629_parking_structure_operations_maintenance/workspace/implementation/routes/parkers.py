"""Parker account endpoints (PRD 3.4)."""
from flask import Blueprint, request

import db
from errors import err_validation
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from services.common import (
    body, require_string, parse_pagination, paginate, get_parker, public_view,
)

bp = Blueprint("parkers", __name__)


@bp.post("/ops/parker-accounts")
def create_parker():
    actor = get_actor()
    require_roles(actor, ["FacilityManager", "ParkingAttendant"])
    payload = body()
    full_name = require_string(payload, "full_name")
    email = require_string(payload, "email")
    for p in db.parker_accounts.values():
        if p["email"] == email:
            raise err_validation("email must be unique across parker accounts")
    ent = {
        "id": db.new_id(),
        "full_name": full_name,
        "email": email,
    }
    db.stamp_new(ent)
    db.parker_accounts[ent["id"]] = ent
    return success_object(public_view(ent), status=201)


@bp.get("/ops/parker-accounts/<parker_account_id>")
def get_parker_route(parker_account_id):
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    return success_object(public_view(get_parker(parker_account_id)))


@bp.get("/ops/parker-accounts")
def list_parkers():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.parker_accounts.values())
    email = request.args.get("email")
    if email is not None:
        items = [p for p in items if p["email"] == email]
    page, total = paginate(items, limit, offset)
    return success_list([public_view(p) for p in page], limit, offset, total)
