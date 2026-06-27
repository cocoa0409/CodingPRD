"""Trade-ins (PRD §3.3)."""
import calc
import errors
from db import db, make_common, touch
from errors import err
from middleware import require_roles
from routes.common import lookup, list_and_respond, respond
from services import serialize_generic
from validation import (
    get_json,
    require_fk,
    require_string,
    require_enum,
    require_int,
)

SR_ADMIN = ("SalesRep", "DealerAdmin")
SR_ADMIN_FM = ("SalesRep", "DealerAdmin", "FinanceManager")


def register(app):

    @app.route("/trade-ins", methods=["POST"])
    @require_roles(*SR_ADMIN)
    def create_tradein():
        body = get_json()
        customer_id = require_fk(body, "customer_id")
        model_code = require_string(body, "model_code")
        serial_number = require_string(body, "serial_number")
        engine_hours = require_int(body, "engine_hours", minimum=0)
        condition_grade = require_enum(body, "condition_grade",
                                       {"EXCELLENT", "GOOD", "FAIR", "POOR"})
        base_value_cents = require_int(body, "base_value_cents", gt=0)
        lookup(db.customers, customer_id)

        appraised = calc.trade_in_appraisal(base_value_cents, condition_grade,
                                             engine_hours)
        tradein = {
            "customer_id": customer_id,
            "model_code": model_code,
            "serial_number": serial_number,
            "engine_hours": engine_hours,
            "appraised_value_cents": appraised,
            "condition_grade": condition_grade,
            "base_value_cents": base_value_cents,
            "minted_unit_id": None,
            "status": "APPRAISED",
        }
        make_common(tradein)
        db.trade_ins[tradein["id"]] = tradein
        return respond(serialize_generic(tradein), status=201)

    @app.route("/trade-ins", methods=["GET"])
    @require_roles(*SR_ADMIN_FM)
    def list_tradeins():
        from flask import request
        items = list(db.trade_ins.values())
        customer_id = request.args.get("customer_id")
        minted_unit_id = request.args.get("minted_unit_id")
        status = request.args.get("status")
        if customer_id is not None:
            items = [t for t in items if t["customer_id"] == customer_id]
        if minted_unit_id is not None:
            items = [t for t in items if t.get("minted_unit_id") == minted_unit_id]
        if status is not None:
            items = [t for t in items if t["status"] == status]
        return list_and_respond(items, serialize_generic)

    @app.route("/trade-ins/<tradein_id>", methods=["GET"])
    @require_roles(*SR_ADMIN_FM)
    def get_tradein(tradein_id):
        tradein = lookup(db.trade_ins, tradein_id)
        return respond(serialize_generic(tradein))

    @app.route("/trade-ins/<tradein_id>/offer", methods=["POST"])
    @require_roles(*SR_ADMIN)
    def offer_tradein(tradein_id):
        tradein = lookup(db.trade_ins, tradein_id)
        if tradein["status"] != "APPRAISED":
            raise err(errors.ERR_INVALID_STATE, "Trade-in is not APPRAISED.")
        tradein["status"] = "OFFERED"
        touch(tradein)
        return respond(serialize_generic(tradein))

    @app.route("/trade-ins/<tradein_id>/decline", methods=["POST"])
    @require_roles(*SR_ADMIN)
    def decline_tradein(tradein_id):
        tradein = lookup(db.trade_ins, tradein_id)
        if tradein["status"] != "OFFERED":
            raise err(errors.ERR_INVALID_STATE, "Trade-in is not OFFERED.")
        tradein["status"] = "DECLINED"
        touch(tradein)
        return respond(serialize_generic(tradein))
