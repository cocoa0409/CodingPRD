from flask import Blueprint

import store
from common import authorize, get_json, need, as_str, as_int
from envelope import object_response
from errors import err

bp = Blueprint("stations", __name__)


@bp.post("/stations")
def create_station():
    authorize(["Manager"])
    body = get_json()
    name = as_str(need(body, "name"), "name")
    seat_capacity = as_int(need(body, "seat_capacity"), "seat_capacity")
    if seat_capacity <= 0:
        raise err("ERR_VALIDATION", "seat_capacity must be > 0")
    s = store.make_record({"name": name, "seat_capacity": seat_capacity})
    store.stations[s["id"]] = s
    return object_response(store.serialize(s), 201)
