"""Order endpoints: place, get, list, cancel, fills (PRD §3.3-§3.6)."""
from decimal import Decimal

from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role, require_account_owner
from models import _base_full, order_dict, fill_dict, touch
from response import object_response, array_response
from routes.common import (get_json_body, get_account, get_security, get_order,
                           paginate, page_slice)
from services.account import recompute_account
from services.order import required_gross_cents, target_quantity, process_fill
from services.position import get_or_create_position
from services.routing import select_venue

bp = Blueprint("orders", __name__)

VALID_SIDES = ("BUY", "SELL")
VALID_TYPES = ("MARKET", "LIMIT")
VALID_SESSIONS = ("REGULAR", "EXTENDED")


@bp.post("/orders")
def place_order():
    user_id, role = get_identity()
    require_role(role, {"AccountHolder"})
    body = get_json_body()

    # ---- existence (left-to-right): account then security (PRD §2.6) ----
    account_id = body.get("account_id")
    if not isinstance(account_id, str) or not account_id:
        raise errors.err(errors.ERR_INVALID_REQUEST, "account_id is required")
    acct = get_account(account_id)
    require_account_owner(role, user_id, acct["id"])

    security_id = body.get("security_id")
    if not isinstance(security_id, str) or not security_id:
        raise errors.err(errors.ERR_INVALID_REQUEST, "security_id is required")
    sec = get_security(security_id)

    # ---- well-formedness (PRD §2.7 priority 4) ----
    side = body.get("side")
    if side not in VALID_SIDES:
        raise errors.err(errors.ERR_INVALID_REQUEST, "side must be BUY or SELL")
    order_type = body.get("order_type")
    if order_type not in VALID_TYPES:
        raise errors.err(errors.ERR_INVALID_REQUEST, "order_type must be MARKET or LIMIT")

    session = body.get("session", "REGULAR")
    if session not in VALID_SESSIONS:
        raise errors.err(errors.ERR_INVALID_REQUEST, "session must be REGULAR or EXTENDED")

    is_closing = body.get("is_closing", False)
    if not isinstance(is_closing, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "is_closing must be a boolean")

    notional = body.get("notional_cents", 0)
    quantity = body.get("quantity", 0)
    if not _is_num(notional) or not _is_num(quantity):
        raise errors.err(errors.ERR_INVALID_REQUEST, "notional_cents and quantity must be numeric")
    notional = int(notional) if notional else 0
    quantity = float(quantity) if quantity else 0.0
    if notional < 0 or quantity < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "amounts must be non-negative")

    # exactly one of notional / quantity (XOR) — both set or both zero is invalid
    has_notional = notional > 0
    has_quantity = quantity > 0
    if has_notional == has_quantity:
        raise errors.err(errors.ERR_INVALID_REQUEST,
                         "exactly one of notional_cents or quantity must be provided")

    limit_price = body.get("limit_price_cents", 0)
    if not _is_num(limit_price):
        raise errors.err(errors.ERR_INVALID_REQUEST, "limit_price_cents must be numeric")
    limit_price = int(limit_price) if limit_price else 0

    # cost_basis_method pins the (account, security) position at first open
    # (default FIFO, PRD §3.5). Carried on the order, applied by the opening fill.
    cost_basis_method = body.get("cost_basis_method", "FIFO")
    if cost_basis_method not in ("FIFO", "AVERAGE"):
        raise errors.err(errors.ERR_INVALID_REQUEST, "cost_basis_method must be FIFO or AVERAGE")

    # ---- OCC (PRD §2.8 priority 5) ----
    expected_version = body.get("expected_account_version")
    if expected_version is None or not isinstance(expected_version, int) or isinstance(expected_version, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "expected_account_version is required")
    if expected_version != acct["version"]:
        raise errors.err(errors.ERR_STALE_ACCOUNT_VERSION, "Account version mismatch")

    # build the order shell (PENDING_NEW)
    order = _base_full()
    order.update({
        "account_id": account_id,
        "security_id": security_id,
        "side": side,
        "order_type": order_type,
        "notional_cents": notional,
        "quantity": quantity,
        "limit_price_cents": limit_price,
        "session": session,
        "is_closing": is_closing,
        "order_status": "PENDING_NEW",
        "filled_quantity": 0.0,
        "filled_notional_cents": 0,
        "reserved_buying_power_cents": 0,
        "pfof_venue": None,
        "opened_day_trade": False,
        "_cost_basis_method": cost_basis_method,
    })

    # ---- business gates (PRD §3.3), in priority order ----
    recompute_account(acct)
    status = acct["trading_status"]

    # priority 7: FROZEN blocks all order placement
    if status == "FROZEN":
        raise errors.err(errors.ERR_ACCOUNT_FROZEN, "Account is FROZEN")

    # priority 8: RESTRICTED_CLOSING_ONLY / MARGIN_CALL — opening BUY blocked
    if status in ("RESTRICTED_CLOSING_ONLY", "MARGIN_CALL"):
        opening_buy = (side == "BUY")
        closing_sell = (side == "SELL" and is_closing)
        if opening_buy or (side == "SELL" and not is_closing):
            raise errors.err(errors.ERR_RESTRICTED_CLOSING_ONLY,
                             "Account restricted to closing activity")

    # priority 9: OPTION requires options_level >= required_options_level
    if sec["instrument_type"] == "OPTION":
        if acct["options_level"] < sec["required_options_level"]:
            raise errors.err(errors.ERR_OPTIONS_LEVEL_INSUFFICIENT,
                             "Insufficient options level")

    # priority 10: LIMIT requires limit_price_cents > 0
    if order_type == "LIMIT" and limit_price <= 0:
        raise errors.err(errors.ERR_LIMIT_PRICE_REQUIRED, "LIMIT order requires limit_price_cents > 0")

    # priority 11: notional order requires fractional_enabled
    if has_notional and not sec["fractional_enabled"]:
        raise errors.err(errors.ERR_FRACTIONAL_NOT_ALLOWED, "Security does not allow fractional orders")

    # priority 12: notional order must be MARKET + REGULAR
    if has_notional and not (order_type == "MARKET" and session == "REGULAR"):
        raise errors.err(errors.ERR_FRACTIONAL_ORDER_CONSTRAINT,
                         "Fractional order must be MARKET and REGULAR session")

    # priority 13: EXTENDED requires extended_hours_eligible AND LIMIT
    if session == "EXTENDED":
        if not sec["extended_hours_eligible"] or order_type != "LIMIT":
            raise errors.err(errors.ERR_EXTENDED_HOURS_LIMIT_ONLY,
                             "Extended-hours order must be LIMIT on an eligible security")

    # priority 14: SELL quantity must not exceed Position.quantity
    if side == "SELL":
        tgt = target_quantity(order, sec)
        pos = _find_position(account_id, security_id)
        available = pos["quantity"] if pos else 0.0
        if Decimal(str(tgt)) > Decimal(str(available)):
            raise errors.err(errors.ERR_INSUFFICIENT_SHARES, "Insufficient shares to sell")

    # priority 15: BUY required_cents must not exceed buying_power
    required = 0
    if side == "BUY":
        required = required_gross_cents(order, sec)
        if required > acct["buying_power_cents"]:
            raise errors.err(errors.ERR_INSUFFICIENT_BUYING_POWER, "Insufficient buying power")

    # ---- all gates pass: ACCEPTED ----
    order["order_status"] = "ACCEPTED"
    order["pfof_venue"] = select_venue(sec["instrument_type"])
    order["_target_quantity"] = target_quantity(order, sec)
    if side == "BUY":
        order["reserved_buying_power_cents"] = required

    db.orders[order["id"]] = order

    # placing an order increments Account.version by 1 (PRD §3.3)
    recompute_account(acct)
    touch(acct)

    return object_response(order_dict(order), 201)


@bp.get("/orders/<order_id>")
def get_order_ep(order_id):
    user_id, role = get_identity()
    require_role(role, {"AccountHolder", "ClearingSystem", "ComplianceOfficer"})
    order = get_order(order_id)
    require_account_owner(role, user_id, order["account_id"])
    return object_response(order_dict(order), 200)


@bp.get("/orders")
def list_orders():
    user_id, role = get_identity()
    require_role(role, {"AccountHolder", "ClearingSystem", "ComplianceOfficer"})

    account_id = request.args.get("account_id")
    security_id = request.args.get("security_id")
    order_status = request.args.get("order_status")

    items = list(db.orders.values())
    if role == "AccountHolder":
        items = [o for o in items if o["account_id"] == user_id]
    if account_id is not None:
        items = [o for o in items if o["account_id"] == account_id]
    if security_id is not None:
        items = [o for o in items if o["security_id"] == security_id]
    if order_status is not None:
        items = [o for o in items if o["order_status"] == order_status]

    limit, offset = paginate()
    page, total = page_slice(items, limit, offset)
    return array_response([order_dict(o) for o in page], limit, offset, total)


@bp.post("/orders/<order_id>/cancel")
def cancel_order(order_id):
    user_id, role = get_identity()
    require_role(role, {"AccountHolder"})
    order = get_order(order_id)
    require_account_owner(role, user_id, order["account_id"])

    if order["order_status"] not in ("ACCEPTED", "PARTIALLY_FILLED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Order is not cancellable")

    order["order_status"] = "CANCELLED"
    order["reserved_buying_power_cents"] = 0  # release remaining reservation
    touch(order)

    acct = db.accounts.get(order["account_id"])
    recompute_account(acct)
    touch(acct)  # increments Account.version by 1
    return object_response(order_dict(order), 200)


@bp.post("/orders/<order_id>/fills")
def report_fill(order_id):
    _, role = get_identity()
    require_role(role, {"ClearingSystem"})
    order = get_order(order_id)
    body = get_json_body()

    # well-formedness
    fq = body.get("fill_quantity")
    fp = body.get("fill_price_cents")
    if not _is_num(fq) or float(fq) <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "fill_quantity must be positive")
    if not isinstance(fp, int) or isinstance(fp, bool) or fp <= 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "fill_price_cents must be a positive integer")

    # state: cannot fill a terminal order
    if order["order_status"] in ("FILLED", "REJECTED", "CANCELLED"):
        raise errors.err(errors.ERR_CANNOT_FILL_TERMINAL, "Order is terminal")

    sec = db.securities.get(order["security_id"])
    acct = db.accounts.get(order["account_id"])
    fill = process_fill(order, sec, acct, float(fq), int(fp))
    return object_response(fill_dict(fill), 201)


@bp.get("/orders/<order_id>/fills")
def list_fills(order_id):
    user_id, role = get_identity()
    require_role(role, {"AccountHolder", "ClearingSystem", "ComplianceOfficer"})
    order = get_order(order_id)
    require_account_owner(role, user_id, order["account_id"])

    items = [f for f in db.fills.values() if f["order_id"] == order_id]
    limit, offset = paginate()
    page, total = page_slice(items, limit, offset)
    return array_response([fill_dict(f) for f in page], limit, offset, total)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _find_position(account_id, security_id):
    for p in db.positions.values():
        if p["account_id"] == account_id and p["security_id"] == security_id:
            return p
    return None
