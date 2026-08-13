"""Location endpoints."""

from flask import Blueprint, request
from middleware import require_role, ALL_ROLES
from response import success_object, success_list
from errors import ApiError, ERR_INVALID_STATE
from db import store
from services.helpers import (
    require_fields, require_int, require_str,
    make_entity, touch, get_location, get_jurisdiction, get_owner,
    list_filtered, paginate, get_pagination_params,
)

bp = Blueprint("locations", __name__)


@bp.route("/locations", methods=["POST"])
def create_location():
    user_id, role = require_role("LocationManager")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["name", "address", "jurisdiction_id", "owner_id",
                             "deposit_floor_cents", "buffer_days", "max_shoot_hours_per_day"])
    jid = require_str(payload, "jurisdiction_id")
    get_jurisdiction(jid)
    oid = require_str(payload, "owner_id")
    get_owner(oid)
    entity = make_entity({
        "name": require_str(payload, "name"),
        "address": require_str(payload, "address"),
        "jurisdiction_id": jid,
        "owner_id": oid,
        "deposit_floor_cents": require_int(payload, "deposit_floor_cents"),
        "buffer_days": require_int(payload, "buffer_days"),
        "max_shoot_hours_per_day": require_int(payload, "max_shoot_hours_per_day"),
        "status": "SCOUTING",
    })
    store.locations[entity["id"]] = entity
    return success_object(entity, 201)


@bp.route("/locations/<lid>", methods=["GET"])
def get_location_by_id(lid):
    user_id, role = require_role(*ALL_ROLES)
    loc = get_location(lid)
    return success_object(loc)


@bp.route("/locations", methods=["GET"])
def list_locations():
    user_id, role = require_role(*ALL_ROLES)
    limit, offset = get_pagination_params(request.args)
    filters = {}
    for f in ("jurisdiction_id", "owner_id", "status"):
        v = request.args.get(f)
        if v:
            filters[f] = v
    items = list_filtered(store.locations, filters)
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/locations/<lid>/retire", methods=["POST"])
def retire_location(lid):
    user_id, role = require_role("LocationManager")
    loc = get_location(lid)
    if loc["status"] not in ("SCOUTING", "AGREEMENT_EXECUTED"):
        raise ApiError(ERR_INVALID_STATE, "Location cannot be retired from current state", 409)
    loc["status"] = "RETIRED"
    touch(loc)
    return success_object(loc)
