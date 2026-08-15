"""Pilot boats."""
from flask import Blueprint, request

from db import DB
from errors import ApiError
from middleware import ANY_ROLE, auth
from response import ok, ok_list
from services import base_entity, boat_status, boat_view
from util import body, pagination_args, paginate, req_int, req_str

bp = Blueprint("boats", __name__)


@bp.post("/pilotage/pilot-boats")
def create_boat():
    auth(["AssociationAdmin"])
    data = body()
    name = req_str(data, "name")
    capacity = req_int(data, "capacity_persons", minimum=1)
    for b in DB["pilot_boats"].values():
        if b["name"] == name:
            raise ApiError("ERR_INVALID_REQUEST", 400, "name must be unique")
    boat = base_entity()
    boat.update({"name": name, "capacity_persons": capacity})
    DB["pilot_boats"][boat["id"]] = boat
    return ok(boat_view(boat), status=201)


@bp.get("/pilotage/pilot-boats")
def list_boats():
    auth(ANY_ROLE)
    limit, offset = pagination_args()
    status = request.args.get("status")
    items = list(DB["pilot_boats"].values())
    if status is not None:
        items = [b for b in items if boat_status(b) == status]
    items.sort(key=lambda b: (b["created_at"], b["_seq"]))
    page, total = paginate(items, limit, offset)
    return ok_list([boat_view(b) for b in page], total, limit, offset)
