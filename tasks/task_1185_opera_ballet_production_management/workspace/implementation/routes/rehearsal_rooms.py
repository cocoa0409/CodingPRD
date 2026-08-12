"""RehearsalRoom routes (PRD 3.6)."""

from flask import Blueprint

from db import store
from middleware import require_roles
from response import ok_object
from routes.common import get_or_404, list_response
from util import json_body, new_record, req_enum, req_int, req_str, to_public

bp = Blueprint("rehearsal_rooms", __name__)

ROOM_KINDS = ("STUDIO", "STAGE", "ORCHESTRA_PIT")


@bp.post("/opera/rehearsal-rooms")
def create_room():
    require_roles("TechnicalDirector")
    body = json_body()
    rec = new_record(
        name=req_str(body, "name"),
        kind=req_enum(body, "kind", ROOM_KINDS),
        capacity=req_int(body, "capacity", min_value=1),
        hourly_rate_cents=req_int(body, "hourly_rate_cents", min_value=0),
    )
    store.rehearsal_rooms[rec["id"]] = rec
    return ok_object(to_public(rec), 201)


@bp.get("/opera/rehearsal-rooms")
def list_rooms():
    require_roles("Any")
    return list_response(store.rehearsal_rooms.values(), [("kind", "kind")])


@bp.get("/opera/rehearsal-rooms/<rid>")
def get_room(rid):
    require_roles("Any")
    return ok_object(to_public(get_or_404(store.rehearsal_rooms, rid,
                                          "RehearsalRoom")))
