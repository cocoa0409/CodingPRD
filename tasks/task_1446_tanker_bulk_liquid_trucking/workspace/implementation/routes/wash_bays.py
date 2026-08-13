"""Wash bays: wash facility master data (PRD 3.1)."""
from flask import Blueprint

from authz import ALL_ROLES, FLEET_ADMIN, require_roles
from db import store
from respond import success
from serialize import ser_wash_bay
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, opt_int, paginate,
    reject_unknown, req_enum_list, req_str, sorted_by_creation,
)

bp = Blueprint("wash_bays", __name__)

WASH_LEVELS = ("FLUSH", "DETERGENT_WASH", "CHEMICAL_KOSHER")


@bp.route("/wash-bays", methods=["POST"])
def create_wash_bay():
    require_roles([FLEET_ADMIN])
    data = json_body()
    reject_unknown(data, {"bay_code", "supported_wash_levels", "cleanup_buffer_minutes"})
    b = {
        "id": new_id(),
        "_seq": next(store.seq),
        "bay_code": req_str(data, "bay_code"),
        "supported_wash_levels": req_enum_list(data, "supported_wash_levels", WASH_LEVELS),
        "cleanup_buffer_minutes": opt_int(data, "cleanup_buffer_minutes", default=30, minimum=0),
    }
    b.update(new_common_fields())
    store.wash_bays[b["id"]] = b
    return success(ser_wash_bay(b), status=201)


@bp.route("/wash-bays", methods=["GET"])
def list_wash_bays():
    require_roles(ALL_ROLES)
    items = sorted_by_creation(list(store.wash_bays.values()))
    page, pagination = paginate(items)
    return success([ser_wash_bay(b) for b in page],
                   response_type="array", pagination=pagination)


@bp.route("/wash-bays/<bid>", methods=["GET"])
def get_wash_bay(bid):
    require_roles(ALL_ROLES)
    return success(ser_wash_bay(get_or_404(store.wash_bays, "wash_bays", bid)))
