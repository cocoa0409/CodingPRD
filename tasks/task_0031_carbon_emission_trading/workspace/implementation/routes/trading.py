"""TradingOrder and Trade endpoints."""

from decimal import Decimal

from flask import Blueprint, request

import clock
import db
import errors
import helpers
import response
from middleware import auth_required, get_actor
from serializers import trading_order_dict, trade_dict
from services.matching import run_matching, _balance_for
from helpers import to_dec, bump


bp = Blueprint("trading", __name__)


VALID_SIDES = {"BUY", "SELL"}
VALID_INSTRUMENTS = {"QUOTA", "CCER"}
VALID_ORDER_TYPES = {"LIMIT", "MARKET"}
VALID_CHANNELS = {"EXCHANGE", "BLOCK", "OTC"}


@bp.route("/trading-orders", methods=["POST"])
@auth_required("Enterprise")
def place_order():
    body = helpers.get_json_body()
    helpers.require_fields(body, ["enterprise_id", "side", "instrument",
                                  "order_type", "quantity", "channel"])
    user_id, _ = get_actor()
    if body["enterprise_id"] != user_id:
        errors.raise_error(errors.ERR_OWNERSHIP_VIOLATION,
                           "Order enterprise_id must match acting user.")
    if body["enterprise_id"] not in db.enterprises:
        errors.raise_error(errors.ERR_NOT_FOUND,
                           f"Enterprise {body['enterprise_id']} not found.")
    if body["side"] not in VALID_SIDES:
        errors.raise_error(errors.ERR_INVALID_INPUT, "Invalid side.")
    if body["instrument"] not in VALID_INSTRUMENTS:
        errors.raise_error(errors.ERR_INVALID_INPUT, "Invalid instrument.")
    if body["order_type"] not in VALID_ORDER_TYPES:
        errors.raise_error(errors.ERR_INVALID_INPUT, "Invalid order_type.")
    if body["channel"] not in VALID_CHANNELS:
        errors.raise_error(errors.ERR_INVALID_INPUT, "Invalid channel.")

    qty = to_dec(body["quantity"])
    if qty <= 0:
        errors.raise_error(errors.ERR_INVALID_ORDER, "quantity must be > 0.")
    limit_price = body.get("limit_price")
    if body["order_type"] == "LIMIT":
        if limit_price is None:
            errors.raise_error(errors.ERR_INVALID_ORDER, "LIMIT order requires limit_price.")
        if to_dec(limit_price) <= 0:
            errors.raise_error(errors.ERR_INVALID_ORDER, "LIMIT order limit_price must be > 0.")
    else:  # MARKET
        if limit_price is not None:
            errors.raise_error(errors.ERR_INVALID_ORDER, "MARKET order must not include limit_price.")

    enterprise = db.enterprises[body["enterprise_id"]]
    if body["side"] == "SELL":
        avail = _balance_for(enterprise, body["instrument"])
        if avail < qty:
            errors.raise_error(errors.ERR_INSUFFICIENT_BALANCE,
                               "Insufficient balance for SELL order.")

    common = helpers.common_create()
    order = {
        "id": db.new_id(),
        "enterprise_id": body["enterprise_id"],
        "side": body["side"],
        "instrument": body["instrument"],
        "order_type": body["order_type"],
        "quantity": qty,
        "limit_price": to_dec(limit_price) if limit_price is not None else None,
        "filled_quantity": Decimal("0"),
        "status": "OPEN",
        "channel": body["channel"],
        "placed_at": clock.now(),
        **common,
    }
    db.trading_orders[order["id"]] = order

    # Run matching engine.
    run_matching(order)

    return response.created(trading_order_dict(order))


@bp.route("/trading-orders/<oid>/cancel", methods=["POST"])
@auth_required("Enterprise")
def cancel_order(oid):
    o = db.trading_orders.get(oid)
    if o is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"TradingOrder {oid} not found.")
    user_id, _ = get_actor()
    if o["enterprise_id"] != user_id:
        errors.raise_error(errors.ERR_OWNERSHIP_VIOLATION, "Cannot cancel another enterprise's order.")
    if o["status"] not in ("OPEN", "PARTIALLY_FILLED"):
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Order must be OPEN or PARTIALLY_FILLED to cancel; is {o['status']}.")
    body = helpers.get_json_body()
    helpers.check_occ(o, body.get("version"))
    o["status"] = "CANCELLED"
    bump(o)
    return response.ok(trading_order_dict(o))


@bp.route("/trading-orders/<oid>", methods=["GET"])
@auth_required("Regulator", "Enterprise")
def read_order(oid):
    o = db.trading_orders.get(oid)
    if o is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"TradingOrder {oid} not found.")
    user_id, user_role = get_actor()
    if user_role == "Enterprise" and o["enterprise_id"] != user_id:
        errors.raise_error(errors.ERR_OWNERSHIP_VIOLATION, "Not your order.")
    return response.ok(trading_order_dict(o))


@bp.route("/trades", methods=["GET"])
@auth_required("Regulator", "Enterprise")
def list_trades():
    limit, offset = helpers.parse_pagination()
    user_id, user_role = get_actor()
    items = list(db.trades.values())
    eid = request.args.get("enterprise_id")
    instrument = request.args.get("instrument")
    channel = request.args.get("channel")
    ea = request.args.get("executed_after")
    eb = request.args.get("executed_before")

    def _enterprise_in_trade(t, e_id):
        bo = db.trading_orders.get(t["buy_order_id"])
        so = db.trading_orders.get(t["sell_order_id"])
        return ((bo and bo["enterprise_id"] == e_id)
                or (so and so["enterprise_id"] == e_id))

    if eid is not None:
        items = [t for t in items if _enterprise_in_trade(t, eid)]
    if instrument is not None:
        items = [t for t in items if t["instrument"] == instrument]
    if channel is not None:
        items = [t for t in items if t["channel"] == channel]
    if ea is not None:
        ea_dt = clock.parse_iso(ea)
        items = [t for t in items if t["executed_at"] >= ea_dt]
    if eb is not None:
        eb_dt = clock.parse_iso(eb)
        items = [t for t in items if t["executed_at"] <= eb_dt]

    if user_role == "Enterprise":
        items = [t for t in items if _enterprise_in_trade(t, user_id)]

    items.sort(key=lambda t: t["created_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok([trade_dict(t) for t in page],
                            limit=limit, offset=offset, total_count=total)
