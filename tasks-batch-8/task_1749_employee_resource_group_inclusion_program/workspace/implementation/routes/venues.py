"""Venue endpoints."""
from flask import Blueprint

from db import STORE
from errors import ApiError, ERR_NOT_FOUND
from middleware import authenticate, body, req_int, req_str
from services import new_entity, venue_json
from util import ok_object

bp = Blueprint("venues", __name__)

ALL_ROLES = ("DeiAdmin", "ExecutiveSponsor", "GroupLeader", "Employee")


def get_venue(venue_id):
    v = STORE["venues"].get(venue_id)
    if v is None:
        raise ApiError(ERR_NOT_FOUND, 404, "venue not found")
    return v


@bp.post("/v1/venues")
def create_venue():
    authenticate(("DeiAdmin",))
    data = body()
    name = req_str(data, "name")
    capacity = req_int(data, "capacity", min_v=1)
    v = new_entity("venues", {"name": name, "capacity": capacity})
    return ok_object(venue_json(v), 201)


@bp.get("/v1/venues/<venue_id>")
def read_venue(venue_id):
    authenticate(ALL_ROLES)
    return ok_object(venue_json(get_venue(venue_id)))
