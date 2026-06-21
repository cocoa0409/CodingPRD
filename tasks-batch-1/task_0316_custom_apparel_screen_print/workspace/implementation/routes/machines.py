"""Press and EmbroideryStation endpoints (PRD §3.2)."""
from flask import Blueprint, request

from db import store, new_common_fields
from errors import err
from middleware import endpoint
from response import success, list_response
from serialize import view, view_list
from validation import get_body, require_str, require_int, parse_pagination, paginate
from services.lookups import get_shop, get_press, get_embroidery_station

bp = Blueprint("machines", __name__)


# ---- Press ----

@bp.route("/presses", methods=["POST"])
@endpoint("ShopManager")
def create_press():
    body = get_body()
    shop_id = require_str(body, "shop_id")
    get_shop(shop_id)
    name = require_str(body, "name")
    teardown = require_int(body, "teardown_buffer_min", default=30)
    if teardown < 0:
        raise err("ERR_INVALID_REQUEST", "teardown_buffer_min must be non-negative")

    press = new_common_fields()
    press.update({"shop_id": shop_id, "name": name, "teardown_buffer_min": teardown})
    store.presses[press["id"]] = press
    return success(view(press), status=201)


@bp.route("/presses/<press_id>", methods=["GET"])
@endpoint("ShopManager", "ArtStaff")
def get_press_route(press_id):
    return success(view(get_press(press_id)), status=200)


@bp.route("/presses", methods=["GET"])
@endpoint("ShopManager", "ArtStaff")
def list_presses():
    limit, offset = parse_pagination()
    shop_id = request.args.get("shop_id")
    items = list(store.presses.values())
    if shop_id is not None:
        items = [p for p in items if p["shop_id"] == shop_id]
    page, total = paginate(items, limit, offset)
    return list_response(view_list(page), limit, offset, total)


# ---- EmbroideryStation ----

@bp.route("/embroidery-stations", methods=["POST"])
@endpoint("ShopManager")
def create_station():
    body = get_body()
    shop_id = require_str(body, "shop_id")
    get_shop(shop_id)
    name = require_str(body, "name")
    head_count = require_int(body, "head_count", default=1)
    if head_count < 1:
        raise err("ERR_INVALID_REQUEST", "head_count must be >= 1")

    station = new_common_fields()
    station.update({"shop_id": shop_id, "name": name, "head_count": head_count})
    store.embroidery_stations[station["id"]] = station
    return success(view(station), status=201)


@bp.route("/embroidery-stations/<station_id>", methods=["GET"])
@endpoint("ShopManager", "ArtStaff")
def get_station_route(station_id):
    return success(view(get_embroidery_station(station_id)), status=200)


@bp.route("/embroidery-stations", methods=["GET"])
@endpoint("ShopManager", "ArtStaff")
def list_stations():
    limit, offset = parse_pagination()
    shop_id = request.args.get("shop_id")
    items = list(store.embroidery_stations.values())
    if shop_id is not None:
        items = [s for s in items if s["shop_id"] == shop_id]
    page, total = paginate(items, limit, offset)
    return list_response(view_list(page), limit, offset, total)
