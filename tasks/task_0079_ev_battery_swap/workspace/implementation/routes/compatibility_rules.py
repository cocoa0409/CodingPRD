"""CompatibilityRule routes."""

from flask import Blueprint, request

from db import DB, new_id
from errors import ERR_DUPLICATE_RESOURCE, ERR_INVALID_INPUT, raise_error
from middleware import auth_required
from response import list_response, success_response
from services.common import (
    get_body,
    get_pagination,
    init_append_only,
    optional_bool,
    paginate,
    require_string,
    sort_by_created_at_asc,
)
from services.lookups import battery_model_by_code, vehicle_model_by_code


bp = Blueprint("compatibility_rules", __name__, url_prefix="/swap-stations")


@bp.route("/compatibility-rules", methods=["POST"])
@auth_required(["PlatformAdmin"])
def create_rule():
    body = get_body()
    vehicle_model_code = require_string(body, "vehicle_model_code")
    battery_model_code = require_string(body, "battery_model_code")
    connector_match = optional_bool(body, "connector_match", True)
    bms_handshake_supported = optional_bool(body, "bms_handshake_supported", True)

    if vehicle_model_by_code(vehicle_model_code) is None:
        raise_error(ERR_INVALID_INPUT, "vehicle_model_code does not exist")
    if battery_model_by_code(battery_model_code) is None:
        raise_error(ERR_INVALID_INPUT, "battery_model_code does not exist")

    for rule in DB["compatibility_rules"].values():
        if (rule.get("vehicle_model_code") == vehicle_model_code
                and rule.get("battery_model_code") == battery_model_code):
            raise_error(ERR_DUPLICATE_RESOURCE,
                        "CompatibilityRule for this pair already exists")

    row = {
        "id": new_id(),
        "vehicle_model_code": vehicle_model_code,
        "battery_model_code": battery_model_code,
        "connector_match": connector_match,
        "bms_handshake_supported": bms_handshake_supported,
    }
    init_append_only(row)
    DB["compatibility_rules"][row["id"]] = row
    return success_response(row, http_status=201)


@bp.route("/compatibility-rules", methods=["GET"])
@auth_required(["PlatformAdmin", "StationOperator", "Member"])
def list_rules():
    limit, offset = get_pagination()
    vmc = request.args.get("vehicle_model_code")
    bmc = request.args.get("battery_model_code")

    items = list(DB["compatibility_rules"].values())
    if vmc is not None:
        items = [r for r in items if r.get("vehicle_model_code") == vmc]
    if bmc is not None:
        items = [r for r in items if r.get("battery_model_code") == bmc]
    items = sort_by_created_at_asc(items)
    sliced, total = paginate(items, limit, offset)
    return list_response(sliced, total, limit, offset)
