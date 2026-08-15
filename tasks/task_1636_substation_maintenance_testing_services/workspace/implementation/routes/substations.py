"""Substation endpoints."""
from flask import Blueprint

import db
from middleware import get_actor, require_roles, ALL_ROLES
from response import success_object, success_list
from errors import err_duplicate_key
from services.common import (
    body, require_string, parse_pagination, paginate, get_substation,
)

bp = Blueprint("substations", __name__)


def substation_view(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "code": s["code"],
        "region": s["region"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.post("/substations")
def create_substation():
    actor = get_actor()
    require_roles(actor, ["OperationsManager"])
    payload = body()
    name = require_string(payload, "name")
    code = require_string(payload, "code")
    region = require_string(payload, "region")
    # Uniqueness: code
    for s in db.substations.values():
        if s["code"] == code:
            raise err_duplicate_key("substation code already exists")
    ent = {
        "id": db.new_id(),
        "name": name,
        "code": code,
        "region": region,
        "status": "ACTIVE",
    }
    db.stamp_new(ent)
    db.substations[ent["id"]] = ent
    return success_object(substation_view(ent), status=201)


@bp.get("/substations")
def list_substations():
    actor = get_actor()
    require_roles(actor, ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.substations.values())
    # Filters
    status = None
    from flask import request
    status = request.args.get("status")
    if status:
        items = [s for s in items if s["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([substation_view(s) for s in page], limit, offset, total)


@bp.post("/substations/<id>/decommission")
def decommission_substation(id):
    actor = get_actor()
    require_roles(actor, ["OperationsManager"])
    sub = get_substation(id)
    if sub["status"] != "ACTIVE":
        from errors import err_state_transition
        raise err_state_transition("Substation is not ACTIVE")
    sub["status"] = "DECOMMISSIONED"
    db.touch(sub)
    return success_object(substation_view(sub))
