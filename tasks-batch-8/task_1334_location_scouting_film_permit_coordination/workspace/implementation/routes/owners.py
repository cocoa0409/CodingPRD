"""LocationOwner endpoints."""

from flask import Blueprint, request
from middleware import require_role, ALL_ROLES
from response import success_object, success_list
from errors import ApiError, ERR_INVALID_REQUEST
from db import store
from services.helpers import (
    require_fields, require_int, require_str,
    make_entity, get_owner, list_filtered, paginate, get_pagination_params,
)

bp = Blueprint("owners", __name__)


@bp.route("/owners", methods=["POST"])
def create_owner():
    user_id, role = require_role("LocationManager")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["legal_name", "contact_email", "default_day_rate_cents"])
    email = require_str(payload, "contact_email")
    # Unique email check
    for o in store.location_owners.values():
        if o.get("contact_email") == email:
            raise ApiError(ERR_INVALID_REQUEST, f"contact_email '{email}' already exists", 400)
    entity = make_entity({
        "legal_name": require_str(payload, "legal_name"),
        "contact_email": email,
        "default_day_rate_cents": require_int(payload, "default_day_rate_cents"),
    })
    store.location_owners[entity["id"]] = entity
    return success_object(entity, 201)


@bp.route("/owners/<oid>", methods=["GET"])
def get_owner_by_id(oid):
    user_id, role = require_role(*ALL_ROLES)
    o = get_owner(oid)
    return success_object(o)


@bp.route("/owners", methods=["GET"])
def list_owners():
    user_id, role = require_role(*ALL_ROLES)
    limit, offset = get_pagination_params(request.args)
    items = list_filtered(store.location_owners)
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)
