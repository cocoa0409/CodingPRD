from flask import Blueprint, request

from db import DB, stamp_new
from errors import not_found, validation
from middleware import (
    as_enum,
    as_number,
    as_string,
    authenticate,
    get_json_body,
    require_customer_ownership,
    require_roles,
)
from response import success_list, success_object
from routes.customers import parse_pagination

bp = Blueprint("assets", __name__)

EQUIPMENT_CLASSES = ["PUMP", "GENERAL_VALVE", "SAFETY_RELIEF_VALVE"]
TEST_STANDARDS = ["API_610_PER_POINT", "SHOP_WEIGHTED_AVG"]


@bp.route("/assets", methods=["POST"])
def create_asset():
    caller = authenticate()
    body = get_json_body()
    require_roles(caller, ["IntakeCoordinator"])
    customer_id = as_string(body, "customer_id")
    serial_number = as_string(body, "serial_number")
    equipment_class = as_enum(body, "equipment_class", EQUIPMENT_CLASSES)
    manufacturer = as_string(body, "manufacturer")
    model = as_string(body, "model")
    rated_flow_gpm = body.get("rated_flow_gpm")
    set_pressure_psig = body.get("set_pressure_psig")
    test_standard = as_enum(body, "test_standard", TEST_STANDARDS, required=False, default="SHOP_WEIGHTED_AVG")

    # Conditional nameplate fields per equipment class
    if equipment_class == "PUMP":
        if rated_flow_gpm is None:
            validation("rated_flow_gpm is required when equipment_class is PUMP")
        if isinstance(rated_flow_gpm, bool) or not isinstance(rated_flow_gpm, (int, float)):
            validation("rated_flow_gpm must be a number")
        if set_pressure_psig is not None:
            validation("set_pressure_psig must be omitted or null when equipment_class is PUMP")
    elif equipment_class == "SAFETY_RELIEF_VALVE":
        if set_pressure_psig is None:
            validation("set_pressure_psig is required when equipment_class is SAFETY_RELIEF_VALVE")
        if isinstance(set_pressure_psig, bool) or not isinstance(set_pressure_psig, (int, float)):
            validation("set_pressure_psig must be a number")
        if rated_flow_gpm is not None:
            validation("rated_flow_gpm must be omitted or null when equipment_class is SAFETY_RELIEF_VALVE")
    else:  # GENERAL_VALVE
        if rated_flow_gpm is not None:
            validation("rated_flow_gpm must be omitted or null when equipment_class is GENERAL_VALVE")
        if set_pressure_psig is not None:
            validation("set_pressure_psig must be omitted or null when equipment_class is GENERAL_VALVE")

    # Existence: customer must exist
    if customer_id not in DB.customers:
        not_found("Customer not found")

    asset = stamp_new(
        {
            "customer_id": customer_id,
            "serial_number": serial_number,
            "equipment_class": equipment_class,
            "manufacturer": manufacturer,
            "model": model,
            "rated_flow_gpm": rated_flow_gpm,
            "set_pressure_psig": set_pressure_psig,
            "test_standard": test_standard,
        }
    )
    DB.assets[asset["id"]] = asset
    return success_object(asset, status=201)


@bp.route("/assets", methods=["GET"])
def list_assets():
    authenticate()
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    items = sorted(DB.assets.values(), key=lambda a: (a["created_at"], a["id"]))
    if customer_id is not None:
        items = [a for a in items if a["customer_id"] == customer_id]
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(page, limit, offset, total)


@bp.route("/assets/<aid>", methods=["GET"])
def get_asset(aid):
    caller = authenticate()
    asset = DB.assets.get(aid)
    if asset is None:
        not_found("Asset not found")
    require_customer_ownership(caller, asset["customer_id"])
    return success_object(asset)
