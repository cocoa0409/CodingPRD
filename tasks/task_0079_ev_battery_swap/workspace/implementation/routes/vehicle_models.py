"""VehicleModel routes."""

from flask import Blueprint

from db import DB, new_id
from errors import ERR_DUPLICATE_RESOURCE, ERR_INVALID_INPUT, raise_error
from middleware import auth_required
from response import success_response
from services.common import (
    get_body,
    init_append_only,
    require_number,
    require_string,
)


bp = Blueprint("vehicle_models", __name__, url_prefix="/swap-stations")


@bp.route("/vehicle-models", methods=["POST"])
@auth_required(["PlatformAdmin"])
def create_vehicle_model():
    body = get_body()
    code = require_string(body, "code", min_len=2, max_len=32)
    name = require_string(body, "name")
    pack_voltage_min = require_number(body, "pack_voltage_min")
    pack_voltage_max = require_number(body, "pack_voltage_max")
    if pack_voltage_min < 0:
        raise_error(ERR_INVALID_INPUT, "pack_voltage_min must be >= 0")
    if pack_voltage_max <= pack_voltage_min:
        raise_error(ERR_INVALID_INPUT, "pack_voltage_max must be > pack_voltage_min")

    for vm in DB["vehicle_models"].values():
        if vm.get("code") == code:
            raise_error(ERR_DUPLICATE_RESOURCE, "VehicleModel code already exists")

    row = {
        "id": new_id(),
        "code": code,
        "name": name,
        "pack_voltage_min": float(pack_voltage_min),
        "pack_voltage_max": float(pack_voltage_max),
    }
    init_append_only(row)
    DB["vehicle_models"][row["id"]] = row
    return success_response(row, http_status=201)
