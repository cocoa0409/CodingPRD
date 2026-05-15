"""BatteryModel routes."""

from flask import Blueprint

from db import DB, new_id
from errors import ERR_DUPLICATE_RESOURCE, ERR_INVALID_INPUT, raise_error
from middleware import auth_required
from response import success_response
from services.common import (
    get_body,
    init_append_only,
    optional_number,
    require_number,
    require_string,
)


bp = Blueprint("battery_models", __name__, url_prefix="/swap-stations")


@bp.route("/battery-models", methods=["POST"])
@auth_required(["PlatformAdmin"])
def create_battery_model():
    body = get_body()
    code = require_string(body, "code", min_len=2, max_len=32)
    rated_capacity_kwh = require_number(body, "rated_capacity_kwh")
    if rated_capacity_kwh <= 0:
        raise_error(ERR_INVALID_INPUT, "rated_capacity_kwh must be > 0")
    nominal_voltage = require_number(body, "nominal_voltage")
    if nominal_voltage <= 0:
        raise_error(ERR_INVALID_INPUT, "nominal_voltage must be > 0")
    manufacturer = require_string(body, "manufacturer")
    ev_soh_floor_pct = optional_number(body, "ev_soh_floor_pct", 80.0)
    if not (0 < ev_soh_floor_pct < 100):
        raise_error(ERR_INVALID_INPUT, "ev_soh_floor_pct must be in (0, 100)")

    for bm in DB["battery_models"].values():
        if bm.get("code") == code:
            raise_error(ERR_DUPLICATE_RESOURCE, "BatteryModel code already exists")

    row = {
        "id": new_id(),
        "code": code,
        "rated_capacity_kwh": float(rated_capacity_kwh),
        "nominal_voltage": float(nominal_voltage),
        "manufacturer": manufacturer,
        "ev_soh_floor_pct": float(ev_soh_floor_pct),
    }
    init_append_only(row)
    DB["battery_models"][row["id"]] = row
    return success_response(row, http_status=201)
