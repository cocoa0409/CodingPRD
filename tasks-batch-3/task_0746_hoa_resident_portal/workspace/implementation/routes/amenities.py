"""Amenity CRUD."""

from flask import Blueprint, request

import db
from auth import require_role
from clock import get_now_iso
from entities import new_amenity
from errors import raise_error
from response import success
from utils import (paginate, require_fields, require_int, require_str,
                   require_json)

bp = Blueprint("amenities", __name__)


@bp.route("/amenities", methods=["POST"])
@require_role("HOAManager")
def create_amenity():
    body = require_json(request)
    require_fields(body, "name", "capacity", "reservation_window_start_hour", "reservation_window_end_hour")
    name = require_str(body, "name")
    capacity = require_int(body, "capacity", minimum=1)
    start_hour = require_int(body, "reservation_window_start_hour", minimum=0, maximum=23)
    end_hour = require_int(body, "reservation_window_end_hour", minimum=1, maximum=24)
    if end_hour <= start_hour:
        raise_error("ERR_INVALID_REQUEST", "reservation_window_end_hour must be > start_hour")
    blackout = body.get("blackout_dates") or []
    if not isinstance(blackout, list) or not all(isinstance(x, str) for x in blackout):
        raise_error("ERR_INVALID_REQUEST", "blackout_dates must be an array of strings")

    row = new_amenity(name, capacity, start_hour, end_hour, blackout, get_now_iso())
    db.amenities[row["id"]] = row
    return success(row, status=201)


@bp.route("/amenities/<aid>", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def get_amenity(aid):
    a = db.amenities.get(aid)
    if not a:
        raise_error("ERR_NOT_FOUND", "amenity not found")
    return success(a)


@bp.route("/amenities/<aid>/reservations", methods=["GET"])
@require_role("Homeowner", "BoardMember", "HOAManager")
def list_amenity_reservations(aid):
    if aid not in db.amenities:
        raise_error("ERR_NOT_FOUND", "amenity not found")
    items = [r for r in db.amenity_reservations.values() if r["amenity_id"] == aid]
    items.sort(key=lambda r: r["created_at"])
    page, meta = paginate(items, request)
    return success(page, is_array=True, pagination=meta)
