"""InventoryUnit routes."""
from flask import request

from db import db, stamp_create
import errors
from errors import err
from middleware import get_user_context, require_role
from response import success
from routes.common import get_or_404, get_json, list_response
from services.util import serialize, require_str, require_int, require_enum
from services.calc import inventory_points_value

SEASONS = {"PLATINUM", "GOLD", "SILVER"}


def serialize_unit(unit):
    return serialize(unit)


def register(app):
    @app.route("/inventory-units", methods=["POST"])
    def create_unit():
        _, role = get_user_context()
        require_role(role, ["ResortManager"])
        data = get_json()
        resort_id = require_str(data, "resort_id")
        unit_label = require_str(data, "unit_label")
        week_number = require_int(data, "week_number")
        if week_number < 1 or week_number > 52:
            raise err(errors.ERR_INVALID_REQUEST, "week_number must be in 1..52.")
        season = require_enum(data, "season", SEASONS)
        resort = get_or_404(db.resorts, resort_id)
        unit = {
            "resort_id": resort_id,
            "unit_label": unit_label,
            "week_number": week_number,
            "season": season,
            "points_value": inventory_points_value(resort, season),
            "status": "AVAILABLE",
        }
        stamp_create(unit)
        db.inventory_units[unit["id"]] = unit
        return success(serialize_unit(unit), status=201)

    @app.route("/inventory-units/<unit_id>", methods=["GET"])
    def get_unit(unit_id):
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        unit = get_or_404(db.inventory_units, unit_id)
        return success(serialize_unit(unit))

    @app.route("/inventory-units", methods=["GET"])
    def list_units():
        _, role = get_user_context()
        require_role(role, ["ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer"])
        items = list(db.inventory_units.values())
        resort_id = request.args.get("resort_id")
        status = request.args.get("status")
        if resort_id is not None:
            items = [u for u in items if u["resort_id"] == resort_id]
        if status is not None:
            items = [u for u in items if u["status"] == status]
        return list_response(items, serialize_unit)
