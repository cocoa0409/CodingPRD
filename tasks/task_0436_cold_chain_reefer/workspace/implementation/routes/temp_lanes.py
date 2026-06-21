"""TempLane endpoints (PRD §3.1). Platform-managed set-point bands."""

from flask import Blueprint, request

from constants import TEMP_LANE_REGULATED_DEFAULT, TEMP_LANE_TOLERANCE_DEFAULT
from db import store
from errors import err
from helpers import get_temp_lane_or_404, pagination_params, paginate
from middleware import authenticate, require_role
from models import serialize, stamp_create
from response import array_response, object_response
from validators import as_bool, as_int, as_number, as_string, get_body, require

bp = Blueprint("temp_lanes", __name__)


@bp.route("/temp-lanes", methods=["POST"])
def create_temp_lane():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})

    body = get_body(request)
    code = as_string(require(body, "code"), "code")
    setpoint_min_c = as_number(require(body, "setpoint_min_c"), "setpoint_min_c")
    setpoint_max_c = as_number(require(body, "setpoint_max_c"), "setpoint_max_c")
    if setpoint_max_c < setpoint_min_c:
        raise err("ERR_INVALID_REQUEST", "setpoint_max_c must be >= setpoint_min_c")

    regulated = TEMP_LANE_REGULATED_DEFAULT
    if body.get("regulated") is not None:
        regulated = as_bool(body["regulated"], "regulated")

    tolerance = TEMP_LANE_TOLERANCE_DEFAULT
    if body.get("tolerance_degree_minutes") is not None:
        tolerance = as_int(
            body["tolerance_degree_minutes"], "tolerance_degree_minutes", minimum=0
        )

    # code globally unique among lanes
    for lane in store.temp_lanes.values():
        if lane["code"] == code:
            raise err("ERR_INVALID_REQUEST", "code must be globally unique among lanes")

    rec = {
        "code": code,
        "setpoint_min_c": setpoint_min_c,
        "setpoint_max_c": setpoint_max_c,
        "regulated": regulated,
        "tolerance_degree_minutes": tolerance,
    }
    stamp_create(rec)
    store.temp_lanes[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/temp-lanes/<lid>", methods=["GET"])
def get_temp_lane(lid):
    _uid, role = authenticate()
    require_role(role, {"Carrier", "Shipper", "ComplianceOfficer", "PlatformAdmin"})
    rec = get_temp_lane_or_404(lid)
    return object_response(serialize(rec), 200)


@bp.route("/temp-lanes", methods=["GET"])
def list_temp_lanes():
    _uid, role = authenticate()
    require_role(role, {"Carrier", "Shipper", "ComplianceOfficer", "PlatformAdmin"})
    limit, offset = pagination_params()

    regulated = request.args.get("regulated")
    records = list(store.temp_lanes.values())
    if regulated is not None:
        if regulated.lower() in ("true", "1"):
            want = True
        elif regulated.lower() in ("false", "0"):
            want = False
        else:
            raise err("ERR_INVALID_REQUEST", "regulated filter must be true/false")
        records = [r for r in records if r["regulated"] is want]

    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)
