from flask import Blueprint

import db
import response
import serializers
from errors import raise_err
from middleware import require_roles
from routes._common import as_decimal, as_str, body, req_field

bp = Blueprint("stations", __name__)


@bp.post("/api/stations")
def create_station():
    require_roles(["COOP_ADMIN"])
    data = body()
    name = as_str(req_field(data, "name"), "name")
    cap = as_decimal(req_field(data, "booking_capacity_tons"), "booking_capacity_tons")
    if cap <= 0:
        raise_err("ERR_INVALID_REQUEST", "booking_capacity_tons must be > 0")
    s = db.stamp_new({
        "name": name,
        "booking_capacity_tons": cap,
        "booked_tons": 0,
        "received_tons": 0,
        "stored_tons": 0,
    })
    db.stations[s["id"]] = s
    return response.success(serializers.station(s), 201)


@bp.get("/api/stations/<station_id>")
def get_station(station_id):
    require_roles(["COOP_ADMIN", "STATION_OPERATOR", "SCHEDULER", "POOL_ACCOUNTANT", "MEMBER"])
    s = db.stations.get(station_id)
    if not s:
        raise_err("ERR_NOT_FOUND", "Station not found")
    return response.success(serializers.station(s), 200)


@bp.get("/api/stations/<station_id>/piles")
def list_station_piles(station_id):
    require_roles(["COOP_ADMIN", "STATION_OPERATOR", "SCHEDULER", "POOL_ACCOUNTANT", "MEMBER"])
    s = db.stations.get(station_id)
    if not s:
        raise_err("ERR_NOT_FOUND", "Station not found")
    piles = [p for p in db.piles.values() if p["station_id"] == station_id]
    piles.sort(key=lambda p: (p["created_at"], p["id"]))
    return response.success_list([serializers.pile(p) for p in piles], len(piles), len(piles), 0, 200)
