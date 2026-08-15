"""WasteStation endpoints: install, list, service."""
from flask import Blueprint

from db import store
from errors import (
    ApiError, ERR_AREA_NOT_FOUND, ERR_WASTE_STATION_NOT_FOUND,
)
from helpers import get_body, req_string, now_iso, parse_pagination, slice_page
from middleware import require_auth
from response import ok
from services import domain

bp = Blueprint("waste_stations", __name__)


def _get_area_or_404(area_id):
    area = store.areas.get(area_id)
    if area is None:
        raise ApiError(ERR_AREA_NOT_FOUND, 404, "Park area not found")
    return area


@bp.route("/dog-park/areas/<areaId>/waste-stations", methods=["POST"])
def install_station(areaId):
    require_auth(["ParkAdmin"])
    body = get_body()
    name = req_string(body, "name")
    _get_area_or_404(areaId)
    station = domain.new_entity(store.waste_stations, {
        "area_id": areaId,
        "name": name,
        "fill_pct": 0,
        "status": "OK",
        "last_serviced_at": None,
    })
    return ok(domain.public(station), 201)


@bp.route("/dog-park/areas/<areaId>/waste-stations", methods=["GET"])
def list_stations(areaId):
    require_auth(["Steward", "ParkAdmin"])
    limit, offset = parse_pagination()
    _get_area_or_404(areaId)
    items = [s for s in store.waste_stations.values() if s["area_id"] == areaId]
    page, meta = slice_page(items, limit, offset)
    return ok([domain.public(s) for s in page], 200, meta)


@bp.route("/dog-park/waste-stations/<stationId>/service", methods=["POST"])
def service_station(stationId):
    require_auth(["Steward", "ParkAdmin"])
    station = store.waste_stations.get(stationId)
    if station is None:
        raise ApiError(ERR_WASTE_STATION_NOT_FOUND, 404, "Waste station not found")
    station["fill_pct"] = 0
    station["status"] = "OK"
    station["last_serviced_at"] = now_iso()
    domain.touch(station)
    return ok(domain.public(station))
