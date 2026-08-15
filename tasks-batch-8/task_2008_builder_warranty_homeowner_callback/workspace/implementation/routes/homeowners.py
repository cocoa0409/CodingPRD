"""Homeowner registration and fetch (PRD 3.1)."""
from flask import Blueprint

from db import db, new_entity
from errors import raise_error, ERR_HOMEOWNER_NOT_FOUND
from middleware import get_caller, require_role
from response import success_object
from util import serialize
from validate import get_body, opt_nullable_str, req_str

bp = Blueprint("homeowners", __name__)


@bp.post("/homeowners")
def create_homeowner():
    _uid, role = get_caller()
    require_role(role, {"WarrantyManager"})
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    phone = opt_nullable_str(body, "phone")
    homeowner = new_entity()
    homeowner.update({
        "full_name": full_name,
        "email": email,
        "phone": phone,
    })
    db["homeowners"][homeowner["id"]] = homeowner
    return success_object(serialize(homeowner), 201)


@bp.get("/homeowners/<rid>")
def fetch_homeowner(rid):
    _uid, role = get_caller()
    require_role(role, {"WarrantyManager", "WarrantyRep", "Homeowner"})
    homeowner = db["homeowners"].get(rid)
    if homeowner is None:
        raise_error(ERR_HOMEOWNER_NOT_FOUND, f"homeowner id does not resolve: {rid}")
    return success_object(serialize(homeowner))
