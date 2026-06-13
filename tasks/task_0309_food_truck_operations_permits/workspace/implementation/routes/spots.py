"""Spot endpoints (PRD §3.3)."""

from flask import Blueprint

import serializers
from db import db
from helpers import (get_body, require_str, require_state_code, require_int,
                     optional_int, get_pagination, paginate)
from lookups import get_spot
from middleware import require_user_context, require_role
from response import ok_object, ok_array

bp = Blueprint("spots", __name__)

WRITE_ROLES = {"Dispatcher", "PlatformAdmin"}
READ_ROLES = {"Dispatcher", "PlatformAdmin", "OperatorTruck", "HealthInspector"}


@bp.post("/spots")
def create_spot():
    user_id, role = require_user_context()
    require_role(role, WRITE_ROLES)
    body = get_body()
    name = require_str(body, "name")
    state_code = require_state_code(body, "state_code")
    concurrent_capacity = require_int(body, "concurrent_capacity", minimum=1)
    reservation_fee_cents = require_int(body, "reservation_fee_cents", minimum=0)
    buffer_minutes = optional_int(body, "buffer_minutes", default=0, minimum=0)
    rec = db.new_record({
        "name": name,
        "state_code": state_code,
        "concurrent_capacity": concurrent_capacity,
        "buffer_minutes": buffer_minutes,
        "reservation_fee_cents": reservation_fee_cents,
    })
    db.spots[rec["id"]] = rec
    return ok_object(serializers.spot(rec), 201)


@bp.get("/spots")
def list_spots():
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    limit, offset = get_pagination()
    window, total = paginate(list(db.spots.values()), limit, offset)
    return ok_array([serializers.spot(r) for r in window], limit, offset, total)


@bp.get("/spots/<spot_id>")
def get_spot_route(spot_id):
    user_id, role = require_user_context()
    require_role(role, READ_ROLES)
    rec = get_spot(spot_id)
    return ok_object(serializers.spot(rec))
