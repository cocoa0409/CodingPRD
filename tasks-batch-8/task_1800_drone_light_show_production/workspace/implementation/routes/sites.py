"""Site endpoints."""

from flask import Blueprint

import errors
import validate as V
from db import DB, new_id, wall_created_at
from middleware import require_role, get_auth
from response import success_object, success_list
from services.show import serialize_site

bp = Blueprint("sites", __name__)


@bp.route("/api/sites", methods=["POST"])
def create_site():
    body = V.get_body()
    V.reject_system_fields(body)
    V.req_fields(body, ["name", "latitude", "longitude", "ground_length_m",
                        "ground_width_m", "site_max_wind_kt", "site_max_gust_kt",
                        "site_max_altitude_ft"])
    uid, role = require_role("ProductionPlanner")

    name = V.req_string(body, "name")
    lat = V.req_number(body, "latitude")
    lng = V.req_number(body, "longitude")
    gl = V.req_number(body, "ground_length_m")
    gw = V.req_number(body, "ground_width_m")
    mw = V.req_number(body, "site_max_wind_kt")
    mg = V.req_number(body, "site_max_gust_kt")
    ma = V.req_number(body, "site_max_altitude_ft")

    if not (-90 <= lat <= 90):
        raise errors.validation("latitude out of range")
    if not (-180 <= lng <= 180):
        raise errors.validation("longitude out of range")
    if gl <= 0 or gw <= 0:
        raise errors.validation("ground dimensions must be > 0")
    if mw <= 0 or mg <= 0 or ma <= 0:
        raise errors.validation("site ceilings must be > 0")

    sid = new_id()
    ts = wall_created_at()
    site = {
        "id": sid, "name": name, "latitude": lat, "longitude": lng,
        "ground_length_m": gl, "ground_width_m": gw,
        "site_max_wind_kt": mw, "site_max_gust_kt": mg,
        "site_max_altitude_ft": ma,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    DB.sites[sid] = site
    DB.insertion_order["sites"].append(sid)
    return success_object(serialize_site(site), 201)


@bp.route("/api/sites/<siteId>", methods=["GET"])
def get_site(siteId):
    get_auth()
    site = DB.sites.get(siteId)
    if site is None:
        raise errors.not_found("ERR_SITE_NOT_FOUND", "site not found")
    return success_object(serialize_site(site))


@bp.route("/api/sites", methods=["GET"])
def list_sites():
    get_auth()
    limit, offset = V.pagination_params()
    items = [DB.sites[i] for i in DB.insertion_order["sites"]]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_site(s) for s in page], limit, offset, total)
