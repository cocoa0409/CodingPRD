"""Owner endpoints (PRD §3.1, §4)."""
from flask import Blueprint

from db import db
from middleware import authenticate, require_role
from response import array_response, object_response
from services.core import stamp_create
from services.reqs import body, paginate, parse_pagination, require_fields
from services.views import (kennel_view, license_view, owner_view, pet_view)

bp = Blueprint("owners", __name__)

ALL_ROLES = {"Owner", "LicensingClerk", "AnimalControlOfficer"}


@bp.route("/owners", methods=["POST"])
def create_owner():
    _, role = authenticate()
    require_role(role, {"LicensingClerk", "Owner"})
    data = body()
    require_fields(data, ["full_name", "email", "address_zip"])
    owner = {
        "full_name": data["full_name"],
        "email": data["email"],
        "address_zip": data["address_zip"],
        "status": "ACTIVE",
        "active_license_count": 0,
        "outstanding_penalty_cents": 0,
    }
    stamp_create(owner)
    db.owners[owner["id"]] = owner
    return object_response(owner_view(owner), status=201)


@bp.route("/owners/<owner_id>", methods=["GET"])
def get_owner(owner_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    owner = db.owners.get(owner_id)
    if owner is None:
        from errors import err
        raise err("ERR_NOT_FOUND", "Owner not found.")
    return object_response(owner_view(owner))


def _list_owner_children(owner_id, role, collection, fk_field, view):
    require_role(role, ALL_ROLES)
    if db.owners.get(owner_id) is None:
        from errors import err
        raise err("ERR_NOT_FOUND", "Owner not found.")
    limit, offset = parse_pagination()
    items = [r for r in collection.values() if r.get(fk_field) == owner_id]
    page, total = paginate(items, limit, offset)
    return array_response([view(r) for r in page], limit, offset, total)


@bp.route("/owners/<owner_id>/pets", methods=["GET"])
def list_owner_pets(owner_id):
    _, role = authenticate()
    return _list_owner_children(owner_id, role, db.pets, "owner_id", pet_view)


@bp.route("/owners/<owner_id>/licenses", methods=["GET"])
def list_owner_licenses(owner_id):
    _, role = authenticate()
    return _list_owner_children(owner_id, role, db.licenses, "owner_id", license_view)


@bp.route("/owners/<owner_id>/kennels", methods=["GET"])
def list_owner_kennels(owner_id):
    _, role = authenticate()
    return _list_owner_children(owner_id, role, db.kennels, "owner_id", kennel_view)
