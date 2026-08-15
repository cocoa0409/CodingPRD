"""Loading racks: terminal rack master data (PRD 3.1)."""
from flask import Blueprint

from authz import ALL_ROLES, FLEET_ADMIN, require_roles
from db import store
from errors import invalid_request
from respond import success
from serialize import ser_rack
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate,
    reject_unknown, req_enum_list, req_int, req_str, sorted_by_creation,
)
from routes.products import COMPATIBILITY_GROUPS

bp = Blueprint("racks", __name__)


@bp.route("/loading-racks", methods=["POST"])
def create_rack():
    require_roles([FLEET_ADMIN])
    data = json_body()
    reject_unknown(data, {"rack_code", "terminal_name", "authorized_groups",
                          "open_hour", "close_hour", "meter_id"})
    open_hour = req_int(data, "open_hour", minimum=0)
    close_hour = req_int(data, "close_hour", minimum=0)
    if open_hour > 23 or close_hour > 23:
        raise invalid_request("open_hour and close_hour must be within 0-23")
    if close_hour <= open_hour:
        raise invalid_request("close_hour must exceed open_hour")
    r = {
        "id": new_id(),
        "_seq": next(store.seq),
        "rack_code": req_str(data, "rack_code"),
        "terminal_name": req_str(data, "terminal_name"),
        "authorized_groups": req_enum_list(data, "authorized_groups", COMPATIBILITY_GROUPS),
        "open_hour": open_hour,
        "close_hour": close_hour,
        "meter_id": req_str(data, "meter_id"),
    }
    r.update(new_common_fields())
    store.racks[r["id"]] = r
    return success(ser_rack(r), status=201)


@bp.route("/loading-racks", methods=["GET"])
def list_racks():
    require_roles(ALL_ROLES)
    items = sorted_by_creation(list(store.racks.values()))
    page, pagination = paginate(items)
    return success([ser_rack(r) for r in page],
                   response_type="array", pagination=pagination)


@bp.route("/loading-racks/<rid>", methods=["GET"])
def get_rack(rid):
    require_roles(ALL_ROLES)
    return success(ser_rack(get_or_404(store.racks, "racks", rid)))
