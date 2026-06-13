"""Order placement, matching cascade, amend, cancel (§3.8)."""
from flask import Blueprint, request

from auth import get_identity, require_roles
from db import db, new_id, next_seq
from errors import err
from response import success
from serializers import order_out, trade_out
from services.common import (
    require_body, required_str, required_number, required_enum, touch,
    available, credit_reserved, debit_available,
)
from services.matching import compute_reserve, run_match, has_resting_sell
from services.orders import cancel_order_internal, release_reserve
from services.pagination import paginate
from numeric import D, decimals_of

bp = Blueprint("orders", __name__)

TIER_RANK = {"TIER_0": 0, "TIER_1": 1, "TIER_2": 2, "TIER_3": 3}


def get_order_or_404(oid):
    o = db.orders.get(oid)
    if o is None:
        raise err("ERR_NOT_FOUND", "Order not found")
    return o


@bp.route("/orders", methods=["POST"])
def place_order():
    user_id, role = get_identity()
    require_roles(role, {"Trader"})
    body = require_body(request.get_json(silent=True))
    account_id = required_str(body, "account_id")
    base_asset = required_str(body, "base_asset")
    quote_asset = required_str(body, "quote_asset")
    side = required_enum(body, "side", {"BUY", "SELL"})
    order_type = required_enum(body, "order_type", {"MARKET", "LIMIT"})
    quantity = required_number(body, "quantity", allow_zero=True)
    limit_price = body.get("limit_price")
    tif = body.get("time_in_force", "GTC")
    if tif is None:
        tif = "GTC"
    if tif not in ("GTC", "IOC"):
        raise err("ERR_INVALID_REQUEST", "time_in_force must be GTC or IOC")
    if "expected_account_version" not in body or body["expected_account_version"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_account_version")
    expected_version = body["expected_account_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise err("ERR_INVALID_REQUEST", "expected_account_version must be an integer")

    # Existence: account, then assets.
    acct = db.accounts.get(account_id)
    if acct is None:
        raise err("ERR_NOT_FOUND", "Account not found")
    if user_id != acct["id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Trader does not own this account")
    base_cfg = db.asset_by_symbol(base_asset)
    if base_cfg is None:
        raise err("ERR_NOT_FOUND", "Base asset not found")
    quote_cfg = db.asset_by_symbol(quote_asset)
    if quote_cfg is None:
        raise err("ERR_NOT_FOUND", "Quote asset not found")

    # Frozen.
    if acct["account_status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_FROZEN", "Account is frozen")

    # KYC tier gate: only the tier failure yields ERR_KYC_TIER_INSUFFICIENT.
    if TIER_RANK.get(acct["kyc_tier"], 0) < 1:
        raise err("ERR_KYC_TIER_INSUFFICIENT", "Trading requires at least TIER_1")
    # Order-shape failures (price presence, positive quantity) yield the
    # order-shape rejection ERR_INVALID_ORDER (PRD §3.8).
    if order_type == "LIMIT":
        if limit_price is None:
            raise err("ERR_INVALID_ORDER", "LIMIT order requires limit_price")
        lp = D(limit_price)
        if lp <= 0:
            raise err("ERR_INVALID_ORDER", "limit_price must be greater than zero")
    else:  # MARKET
        if limit_price is not None:
            raise err("ERR_INVALID_ORDER", "MARKET order must not carry limit_price")
    if quantity <= 0:
        raise err("ERR_INVALID_ORDER", "quantity must be greater than zero")

    # Pair validity + precision.
    if base_asset == quote_asset:
        raise err("ERR_INVALID_ORDER", "base_asset and quote_asset must differ")
    if decimals_of(quantity) > base_cfg["decimals"]:
        raise err("ERR_INVALID_ORDER", "quantity exceeds base asset precision")
    if order_type == "LIMIT" and decimals_of(D(limit_price)) > quote_cfg["decimals"]:
        raise err("ERR_INVALID_ORDER", "limit_price exceeds quote asset precision")

    # MARKET BUY requires resting SELL book.
    if order_type == "MARKET" and side == "BUY":
        if not has_resting_sell(base_asset, quote_asset):
            raise err("ERR_NO_LIQUIDITY", "No resting sell liquidity")

    # OCC against account version.
    if expected_version != acct["version"]:
        raise err("ERR_STALE_ACCOUNT_VERSION", "Stale account version")

    now = db.clock.now()
    order = {
        "id": new_id(),
        "account_id": account_id,
        "base_asset": base_asset,
        "quote_asset": quote_asset,
        "side": side,
        "order_type": order_type,
        "limit_price": D(limit_price) if limit_price is not None else None,
        "quantity": quantity,
        "filled_quantity": D(0),
        "avg_fill_price": None,
        "reserved_remaining": D(0),
        "lifecycle_status": "OPEN",
        "time_in_force": tif,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }

    # Reserve worst-case funds.
    reserve_asset, reserve_qty = compute_reserve(order, base_cfg, quote_cfg)
    bal = db.get_or_create_balance(account_id, reserve_asset)
    if available(bal) < reserve_qty:
        raise err("ERR_INSUFFICIENT_AVAILABLE", "Insufficient available to reserve")

    # Commit: lock reserve, register order, run matching.
    debit_available(bal, reserve_qty)
    credit_reserved(bal, reserve_qty)
    order["reserved_remaining"] = reserve_qty
    db.orders[order["id"]] = order

    run_match(order, base_cfg, quote_cfg)

    # IOC leftover cancels; GTC LIMIT leftover rests.
    if order["lifecycle_status"] in ("OPEN", "PARTIALLY_FILLED"):
        if tif == "IOC":
            cancel_order_internal(order)
        else:
            # GTC LIMIT rests on book. For a MARKET order with leftover (rare,
            # only possible if not fully filled and not IOC) there is no posted
            # price to rest at; treat as cancelled remainder.
            if order_type == "MARKET":
                cancel_order_internal(order)

    # Placing an order bumps the account version.
    touch(acct)
    return success(order_out(order), status=201)


@bp.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator"})
    o = get_order_or_404(oid)
    return success(order_out(o))


@bp.route("/orders", methods=["GET"])
def list_orders():
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator"})
    items = list(db.orders.values())
    for key in ("account_id", "base_asset", "quote_asset", "lifecycle_status", "side"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o.get(key) == val]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    page, pag = paginate(items)
    return success([order_out(o) for o in page], pagination=pag)


@bp.route("/orders/<oid>", methods=["PATCH"])
def amend_order(oid):
    user_id, role = get_identity()
    require_roles(role, {"Trader"})
    o = get_order_or_404(oid)
    if user_id != o["account_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Trader does not own this order")
    body = require_body(request.get_json(silent=True))
    if "expected_order_version" not in body or body["expected_order_version"] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: expected_order_version")
    expected_version = body["expected_order_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise err("ERR_INVALID_REQUEST", "expected_order_version must be an integer")

    if o["lifecycle_status"] not in ("OPEN", "PARTIALLY_FILLED"):
        raise err("ERR_INVALID_STATE", "Only resting orders may be amended")
    if o["order_type"] != "LIMIT":
        raise err("ERR_INVALID_STATE", "Only LIMIT orders may be amended")

    base_cfg = db.asset_by_symbol(o["base_asset"])
    quote_cfg = db.asset_by_symbol(o["quote_asset"])

    new_price = body.get("limit_price")
    new_qty = body.get("quantity")

    if new_price is not None:
        if isinstance(new_price, bool) or not isinstance(new_price, (int, float)):
            raise err("ERR_INVALID_REQUEST", "limit_price must be a number")
        if D(new_price) <= 0:
            raise err("ERR_INVALID_ORDER", "limit_price must be greater than zero")
        if decimals_of(D(new_price)) > quote_cfg["decimals"]:
            raise err("ERR_INVALID_ORDER", "limit_price exceeds quote asset precision")
    if new_qty is not None:
        if isinstance(new_qty, bool) or not isinstance(new_qty, (int, float)):
            raise err("ERR_INVALID_REQUEST", "quantity must be a number")
        if D(new_qty) <= 0:
            raise err("ERR_INVALID_ORDER", "quantity must be greater than zero")
        if D(new_qty) < D(o["filled_quantity"]):
            raise err("ERR_INVALID_ORDER", "quantity below already-filled quantity")
        if decimals_of(D(new_qty)) > base_cfg["decimals"]:
            raise err("ERR_INVALID_ORDER", "quantity exceeds base asset precision")

    # OCC against the order's own version.
    if expected_version != o["version"]:
        raise err("ERR_STALE_ACCOUNT_VERSION", "Stale order version")

    if new_price is not None:
        o["limit_price"] = D(new_price)
    if new_qty is not None:
        o["quantity"] = D(new_qty)

    # Re-reserve: release current reserve and lock the new worst-case.
    release_reserve(o)
    remaining_qty = D(o["quantity"]) - D(o["filled_quantity"])
    if remaining_qty > 0:
        probe = dict(o)
        probe["quantity"] = remaining_qty
        reserve_asset, reserve_qty = compute_reserve(probe, base_cfg, quote_cfg)
        bal = db.get_or_create_balance(o["account_id"], reserve_asset)
        if available(bal) < reserve_qty:
            raise err("ERR_INSUFFICIENT_AVAILABLE", "Insufficient available to re-reserve")
        debit_available(bal, reserve_qty)
        credit_reserved(bal, reserve_qty)
        o["reserved_remaining"] = reserve_qty

    touch(o)
    run_match(o, base_cfg, quote_cfg)
    if o["lifecycle_status"] in ("OPEN", "PARTIALLY_FILLED") and o["time_in_force"] == "IOC":
        cancel_order_internal(o)
    return success(order_out(o))


@bp.route("/orders/<oid>", methods=["DELETE"])
def cancel_order(oid):
    user_id, role = get_identity()
    require_roles(role, {"Trader"})
    o = get_order_or_404(oid)
    if user_id != o["account_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Trader does not own this order")
    if o["lifecycle_status"] not in ("OPEN", "PARTIALLY_FILLED"):
        raise err("ERR_INVALID_STATE", "Order cannot be cancelled from its current state")
    cancel_order_internal(o)
    return success(order_out(o))


@bp.route("/trades", methods=["GET"])
def list_trades():
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator"})
    items = list(db.trades.values())
    for key in ("maker_order_id", "taker_order_id", "base_asset", "quote_asset"):
        val = request.args.get(key)
        if val is not None:
            items = [t for t in items if t.get(key) == val]
    items.sort(key=lambda t: (t["created_at"], t["_seq"]))
    page, pag = paginate(items)
    return success([trade_out(t) for t in page], pagination=pag)


@bp.route("/trades/<tid>", methods=["GET"])
def get_trade(tid):
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator"})
    t = db.trades.get(tid)
    if t is None:
        raise err("ERR_NOT_FOUND", "Trade not found")
    return success(trade_out(t))
