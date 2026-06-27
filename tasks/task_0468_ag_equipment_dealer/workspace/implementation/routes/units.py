"""Units (PRD §3.1)."""
import errors
from db import db, make_common, touch
from errors import err
from middleware import require_roles
from routes.common import lookup, list_and_respond, respond
from services import serialize_unit
from validation import (
    get_json,
    require_string,
    require_enum,
    require_int,
    optional_int,
)

ALL_ROLES = ("DealerAdmin", "SalesRep", "ServiceAdvisor", "PartsClerk",
             "FinanceManager", "AuctionClerk")


def register(app):

    @app.route("/units", methods=["POST"])
    @require_roles("DealerAdmin", "SalesRep")
    def create_unit():
        body = get_json()
        stock_number = require_string(body, "stock_number")
        condition = require_enum(body, "condition", {"NEW", "USED"})
        model_code = require_string(body, "model_code")
        serial_number = require_string(body, "serial_number")
        dealer_cost_cents = require_int(body, "dealer_cost_cents", minimum=0)
        list_price_cents = require_int(body, "list_price_cents", minimum=0)
        engine_hours = optional_int(body, "engine_hours", default=0, minimum=0)

        # uniqueness (priority 5) after field validation (priority 4)
        for u in db.units.values():
            if u["stock_number"] == stock_number:
                raise err(errors.ERR_DUPLICATE_KEY, "stock_number already exists.")
            if u["serial_number"] == serial_number:
                raise err(errors.ERR_DUPLICATE_KEY, "serial_number already exists.")

        unit = {
            "stock_number": stock_number,
            "condition": condition,
            "model_code": model_code,
            "serial_number": serial_number,
            "dealer_cost_cents": dealer_cost_cents,
            "list_price_cents": list_price_cents,
            "engine_hours": engine_hours,
            "acquired_from_tradein_id": None,
            "floor_planned": False,
            "status": "AVAILABLE",
        }
        make_common(unit)
        db.units[unit["id"]] = unit
        return respond(serialize_unit(unit), status=201)

    @app.route("/units", methods=["GET"])
    @require_roles(*ALL_ROLES)
    def list_units():
        from flask import request
        items = list(db.units.values())
        status = request.args.get("status")
        condition = request.args.get("condition")
        model_code = request.args.get("model_code")
        acquired = request.args.get("acquired_from_tradein_id")
        if status is not None:
            items = [u for u in items if u["status"] == status]
        if condition is not None:
            items = [u for u in items if u["condition"] == condition]
        if model_code is not None:
            items = [u for u in items if u["model_code"] == model_code]
        if acquired is not None:
            items = [u for u in items if u.get("acquired_from_tradein_id") == acquired]
        return list_and_respond(items, serialize_unit)

    @app.route("/units/<unit_id>", methods=["GET"])
    @require_roles(*ALL_ROLES)
    def get_unit(unit_id):
        unit = lookup(db.units, unit_id)
        return respond(serialize_unit(unit))

    @app.route("/units/<unit_id>/recondition", methods=["POST"])
    @require_roles("DealerAdmin")
    def recondition_unit(unit_id):
        unit = lookup(db.units, unit_id)
        if unit["status"] != "REPOSSESSED":
            raise err(errors.ERR_INVALID_STATE, "Unit is not REPOSSESSED.")
        unit["status"] = "AVAILABLE"
        touch(unit)
        return respond(serialize_unit(unit))

    @app.route("/units/<unit_id>/retire", methods=["POST"])
    @require_roles("DealerAdmin")
    def retire_unit(unit_id):
        unit = lookup(db.units, unit_id)
        if unit["status"] != "AVAILABLE" or unit["floor_planned"]:
            raise err(errors.ERR_INVALID_STATE,
                      "Unit must be AVAILABLE and not floor-planned to retire.")
        unit["status"] = "RETIRED"
        touch(unit)
        return respond(serialize_unit(unit))
