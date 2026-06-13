"""Owner directory endpoints (PRD §3.2)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import APIError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import require_roles
from response import ok_object
from services import common
from services.registration_svc import mint_lean, public

bp = Blueprint("owners", __name__)


@bp.post("/owners")
def create_owner():
    require_roles(["WarrantyAdmin"])
    body = common.get_json_body()
    common.require_fields(body, ["full_name", "email"])
    full_name = common.require_str(body, "full_name")
    email = common.require_str(body, "email")

    # email unique
    for o in db.owners.values():
        if o["email"] == email:
            raise APIError(ERR_INVALID_REQUEST, 400, "email already exists")

    owner = {"full_name": full_name, "email": email}
    mint_lean(owner)
    db.owners[owner["id"]] = owner
    return ok_object(public(owner), 201)


@bp.get("/owners/<oid>")
def get_owner(oid):
    require_roles(["WarrantyAdmin", "Owner"])
    owner = db.owners.get(oid)
    if owner is None:
        raise APIError(ERR_NOT_FOUND, 404, "Owner not found")
    return ok_object(public(owner))
