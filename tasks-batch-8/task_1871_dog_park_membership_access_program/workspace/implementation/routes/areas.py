"""ParkArea endpoints: create, list, read."""
from flask import Blueprint

from db import store
from errors import ApiError, ERR_INVALID_REQUEST, ERR_AREA_NOT_FOUND
from helpers import get_body, req_string, req_enum, req_int, paginate
from middleware import require_auth
from response import ok
from services import domain

bp = Blueprint("areas", __name__)


def _get_area_or_404(area_id):
    area = store.areas.get(area_id)
    if area is None:
        raise ApiError(ERR_AREA_NOT_FOUND, 404, "Park area not found")
    return area


def _parse_peak_windows(body):
    windows = body.get("peak_windows", [])
    if windows is None:
        windows = []
    if not isinstance(windows, list):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "peak_windows must be an array of minute-of-day ranges")
    parsed = []
    for w in windows:
        if not isinstance(w, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Each peak window must be an object")
        start = w.get("start_minute")
        end = w.get("end_minute")
        if (not isinstance(start, int) or isinstance(start, bool)
                or not isinstance(end, int) or isinstance(end, bool)):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "start_minute and end_minute must be integers")
        if not (0 <= start < end <= 1440):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Peak window requires 0 <= start_minute < end_minute <= 1440")
        parsed.append({"start_minute": start, "end_minute": end})
    return parsed


@bp.route("/dog-park/areas", methods=["POST"])
def create_area():
    require_auth(["ParkAdmin"])
    body = get_body()
    name = req_string(body, "name")
    restriction = req_enum(body, "size_class_restriction", ("SMALL", "LARGE"))
    capacity = req_int(body, "capacity")
    if capacity <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "capacity must be > 0")
    peak_capacity = req_int(body, "peak_capacity")
    if peak_capacity < 0 or peak_capacity > capacity:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "peak_capacity must be between 0 and capacity")
    peak_windows = _parse_peak_windows(body)
    area = domain.new_entity(store.areas, {
        "name": name,
        "size_class_restriction": restriction,
        "capacity": capacity,
        "peak_capacity": peak_capacity,
        "peak_windows": peak_windows,
    })
    return ok(domain.area_view(area), 201)


@bp.route("/dog-park/areas", methods=["GET"])
def list_areas():
    require_auth(["Member", "Steward", "ParkAdmin"])
    page, meta = paginate(list(store.areas.values()))
    return ok([domain.area_view(a) for a in page], 200, meta)


@bp.route("/dog-park/areas/<areaId>", methods=["GET"])
def get_area(areaId):
    require_auth(["Member", "Steward", "ParkAdmin"])
    area = _get_area_or_404(areaId)
    return ok(domain.area_view(area))
