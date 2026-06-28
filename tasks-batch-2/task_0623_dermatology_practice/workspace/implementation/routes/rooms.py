"""Rooms (PRD 3.1)."""
from flask import Blueprint

import db
import helpers
import response
from middleware import require

bp = Blueprint("rooms", __name__)

ROOM_KINDS = {"STANDARD", "MOHS_SUITE"}


@bp.post("/rooms")
@require("PracticeAdmin")
def create_room():
    data = helpers.body()
    name = helpers.require_str(data, "name")
    room_kind = helpers.require_enum(data, "room_kind", ROOM_KINDS)
    buffer = helpers.opt_int(data, "turnover_buffer_minutes", 0)
    if buffer < 0:
        raise helpers.errors.invalid_request("turnover_buffer_minutes must be >= 0")
    row = {
        "name": name,
        "room_kind": room_kind,
        "turnover_buffer_minutes": buffer,
    }
    db.stamp_new(row)
    db.rooms[row["id"]] = row
    return response.created(row)


@bp.get("/rooms/<rid>")
@require("PracticeAdmin", "FrontDesk", "Provider")
def get_room(rid):
    row = helpers.get_or_404(db.rooms, rid, "room")
    return response.ok(row)


@bp.get("/rooms")
@require("PracticeAdmin", "FrontDesk", "Provider")
def list_rooms():
    page, limit, offset, total = helpers.paginate(list(db.rooms.values()))
    return response.listing(page, limit, offset, total)
