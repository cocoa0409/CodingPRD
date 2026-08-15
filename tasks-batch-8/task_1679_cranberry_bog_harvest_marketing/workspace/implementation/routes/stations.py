"""ReceivingStation endpoints: register, get."""
from flask import Blueprint

from db import store, new_common
from errors import ApiError
from middleware import authenticate, require_roles, ANY_ROLE
from response import ok, created
from validation import get_body, req_string, req_int, require_positive

bp = Blueprint("stations", __name__)


@bp.post("/coop/stations")
def create_station():
    body = get_body()
    name = req_string(body, "name")
    capacity = require_positive(req_int(body, "daily_capacity_barrels"),
                                "daily_capacity_barrels")

    _, role = authenticate()
    require_roles(role, {"CoopAdmin"})

    station = new_common({
        "name": name,
        "daily_capacity_barrels": capacity,
    })
    store.stations[station["id"]] = station
    return created(station)


@bp.get("/coop/stations/<station_id>")
def get_station(station_id):
    _, role = authenticate()
    require_roles(role, ANY_ROLE)
    station = store.stations.get(station_id)
    if station is None:
        raise ApiError("ERR_NOT_FOUND", 404, "ReceivingStation not found")
    return ok(station)
