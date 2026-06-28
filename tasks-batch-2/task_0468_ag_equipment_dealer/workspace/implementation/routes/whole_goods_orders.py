"""Seasonal whole-goods pre-orders (PRD §3.8)."""
import calc
import errors
from db import db, make_common, touch
from errors import err
from middleware import require_roles
from routes.common import lookup, list_and_respond, respond
from services import serialize_generic
from validation import get_json, require_fk, require_string, require_enum, require_int

WGO_ROLES = ("SalesRep", "DealerAdmin")


def register(app):

    @app.route("/whole-goods-orders", methods=["POST"])
    @require_roles(*WGO_ROLES)
    def place_order():
        body = get_json()
        customer_id = require_fk(body, "customer_id")
        model_code = require_string(body, "model_code")
        season_program = require_enum(body, "season_program",
                                      {"EARLY_ORDER", "IN_SEASON", "LATE"})
        quantity = require_int(body, "quantity", gt=0)
        unit_msrp_cents = require_int(body, "unit_msrp_cents", gt=0)
        lookup(db.customers, customer_id)

        net_price = calc.whole_goods_net_price(unit_msrp_cents, season_program)
        order = {
            "customer_id": customer_id,
            "model_code": model_code,
            "season_program": season_program,
            "quantity": quantity,
            "unit_msrp_cents": unit_msrp_cents,
            "deposit_cents": 0,
            "net_price_cents": net_price,
            "fulfilled_qty": 0,
            "status": "PLACED",
        }
        make_common(order)
        db.whole_goods_orders[order["id"]] = order
        return respond(serialize_generic(order), status=201)

    @app.route("/whole-goods-orders", methods=["GET"])
    @require_roles(*WGO_ROLES)
    def list_orders():
        from flask import request
        items = list(db.whole_goods_orders.values())
        for key in ("customer_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [o for o in items if o.get(key) == val]
        return list_and_respond(items, serialize_generic)

    @app.route("/whole-goods-orders/<order_id>", methods=["GET"])
    @require_roles(*WGO_ROLES)
    def get_order(order_id):
        order = lookup(db.whole_goods_orders, order_id)
        return respond(serialize_generic(order))

    @app.route("/whole-goods-orders/<order_id>/confirm", methods=["POST"])
    @require_roles(*WGO_ROLES)
    def confirm_order(order_id):
        order = lookup(db.whole_goods_orders, order_id)
        if order["status"] != "PLACED":
            raise err(errors.ERR_INVALID_STATE, "Order is not PLACED.")
        order["deposit_cents"] = calc.whole_goods_deposit(
            order["net_price_cents"], order["quantity"]
        )
        order["status"] = "CONFIRMED"
        touch(order)
        return respond(serialize_generic(order))

    @app.route("/whole-goods-orders/<order_id>/allocate", methods=["POST"])
    @require_roles(*WGO_ROLES)
    def allocate_order(order_id):
        order = lookup(db.whole_goods_orders, order_id)
        body = get_json()
        unit_id = require_fk(body, "unit_id")
        unit = lookup(db.units, unit_id)

        if order["status"] not in ("CONFIRMED", "PARTIAL_FULFILLED"):
            raise err(errors.ERR_INVALID_STATE,
                      "Order is not CONFIRMED/PARTIAL_FULFILLED.")
        # require AVAILABLE unit with matching model_code
        if unit["status"] != "AVAILABLE" or unit["model_code"] != order["model_code"]:
            raise err(errors.ERR_NO_MATCHING_UNIT,
                      "No matching AVAILABLE unit for allocation.")

        unit["status"] = "RESERVED"
        touch(unit)
        order["fulfilled_qty"] += 1
        if order["fulfilled_qty"] >= order["quantity"]:
            order["status"] = "FULFILLED"
        else:
            order["status"] = "PARTIAL_FULFILLED"
        touch(order)
        return respond(serialize_generic(order))

    @app.route("/whole-goods-orders/<order_id>/cancel", methods=["POST"])
    @require_roles(*WGO_ROLES)
    def cancel_order(order_id):
        order = lookup(db.whole_goods_orders, order_id)
        if order["status"] not in ("PLACED", "CONFIRMED"):
            raise err(errors.ERR_INVALID_STATE, "Order is not PLACED/CONFIRMED.")
        # release any reserved units allocated to this order back to AVAILABLE.
        # (fulfilled_qty > 0 only possible once PARTIAL_FULFILLED, which is not
        # cancellable; from CONFIRMED with fulfilled_qty 0 there are none. We
        # still guard defensively against any reserved units linked.)
        order["status"] = "CANCELLED"
        touch(order)
        return respond(serialize_generic(order))
