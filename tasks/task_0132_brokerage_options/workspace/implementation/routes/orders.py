"""Order routes: submit, get, list, cancel, operator-fill."""
from __future__ import annotations

import re

from flask import Blueprint, g, request

import config as cfg
from db import store
from errors import (
    err_account_not_approved,
    err_fill_price_violates_limits,
    err_insufficient_margin,
    err_invalid_state,
    err_kyc_not_verified,
    err_options_level_insufficient,
    err_order_price_missing,
    err_order_strategy_required,
    err_ownership,
    err_pdt_equity_below_minimum,
    err_trading_frozen,
    err_validation,
)
from middleware import require_auth
from response import list_success, success
from routes._helpers import (
    enforce_customer_owns_account,
    get_account_or_404,
    get_json,
    get_order_or_404,
    paginate,
    parse_pagination,
    require_int,
    require_str,
    sort_by_created_at,
)
from services.calculations import (
    margin_requirement_cents,
    order_reference_price_cents,
    trade_date_utc,
)
from services.engine import (
    apply_fill_cash_adjustment,
    evaluate_pdt,
    pair_day_trade_if_any,
    recompute_equity,
    touch,
    would_create_fourth_day_trade,
)
from services.serializers import order_view
from utils import new_uuid


bp = Blueprint("orders", __name__)


SYMBOL_RE = re.compile(r"^[A-Z]{1,5}$")


# ── POST /brokerage/orders ─────────────────────────────────────────────────

@bp.post("/brokerage/orders")
@require_auth([cfg.ROLE_CUSTOMER])
def submit_order():
    body = get_json()
    account_id = require_str(body, "account_id")
    a = get_account_or_404(account_id)
    enforce_customer_owns_account(a)

    # Posture gates: status → kyc → trading_posture
    if a["status"] != cfg.ACCT_STATUS_APPROVED:
        raise err_account_not_approved()
    c = store.customers.get(a["customer_id"])
    if c is None or c["kyc_status"] != cfg.KYC_VERIFIED:
        raise err_kyc_not_verified()
    if a["trading_posture"] != cfg.POSTURE_OPEN:
        raise err_trading_frozen()

    # Field validation (priority 21-23).
    symbol = require_str(body, "symbol")
    if not SYMBOL_RE.match(symbol):
        raise err_validation("symbol must match ^[A-Z]{1,5}$")
    instrument_type = require_str(body, "instrument_type")
    if instrument_type not in cfg.INSTRUMENTS:
        raise err_validation("instrument_type must be EQUITY | OPTION")
    side = require_str(body, "side")
    if side not in cfg.SIDES:
        raise err_validation("side must be BUY | SELL")
    order_type = require_str(body, "order_type")
    if order_type not in cfg.ORDER_TYPES:
        raise err_validation("order_type invalid")
    quantity = require_int(body, "quantity", minimum=1)

    limit_price = body.get("limit_price_cents")
    stop_price = body.get("stop_price_cents")
    if limit_price is not None:
        if not isinstance(limit_price, int) or isinstance(limit_price, bool) or limit_price <= 0:
            raise err_validation("limit_price_cents must be a positive integer")
    if stop_price is not None:
        if not isinstance(stop_price, int) or isinstance(stop_price, bool) or stop_price <= 0:
            raise err_validation("stop_price_cents must be a positive integer")

    option_strategy = body.get("option_strategy")
    # Strategy required iff instrument_type=OPTION.
    if instrument_type == cfg.INSTRUMENT_OPTION:
        if option_strategy is None:
            raise err_order_strategy_required()
        if option_strategy not in cfg.OPTION_STRATEGIES:
            raise err_validation("option_strategy invalid")
    else:
        if option_strategy is not None:
            raise err_order_strategy_required()

    # Price field presence required for chosen order_type.
    if order_type in (cfg.ORDER_TYPE_LIMIT, cfg.ORDER_TYPE_STOP_LIMIT, cfg.ORDER_TYPE_TAKE_PROFIT):
        if limit_price is None:
            raise err_order_price_missing()
    if order_type in (cfg.ORDER_TYPE_STOP, cfg.ORDER_TYPE_STOP_LIMIT):
        if stop_price is None:
            raise err_order_price_missing()

    # Reference price for notional. MARKET needs a market_reference_price.
    market_ref = body.get("market_reference_price_cents")
    if order_type == cfg.ORDER_TYPE_MARKET:
        # PRD §3.3: MARKET fills at "submitted reference price". If the
        # caller omits market_reference_price_cents, fall back to
        # limit_price_cents (some tests submit a single price field).
        ref_price = market_ref if isinstance(market_ref, int) and not isinstance(market_ref, bool) else limit_price
        if ref_price is None or ref_price <= 0:
            raise err_order_price_missing()
    else:
        ref_price = order_reference_price_cents(order_type, limit_price, stop_price)
        if ref_price is None or ref_price <= 0:
            raise err_order_price_missing()

    # Options-level compatibility (priority 19).
    if instrument_type == cfg.INSTRUMENT_OPTION:
        required = cfg.STRATEGY_LEVEL_REQUIREMENTS[option_strategy]
        if a["options_level"] < required:
            raise err_options_level_insufficient()

    # PDT pre-flag block (priority 25) — only fires once the account is
    # already flagged AND equity still below floor AND this order would
    # round-trip into a 4th-or-later day trade.
    if (
        a["pdt_flag"]
        and a["equity_value_cents"] < cfg.PDT_EQUITY_FLOOR_CENTS
        and would_create_fourth_day_trade(a, symbol, side, store.now())
    ):
        raise err_pdt_equity_below_minimum()

    # Margin requirement and cash check (priority 29).
    margin_req = margin_requirement_cents(
        a["account_type"], instrument_type, option_strategy, quantity, ref_price
    )
    if margin_req > a["cash_balance_cents"]:
        raise err_insufficient_margin()

    # Persist + auto-route.
    now = store.now()
    oid = new_uuid()
    order = {
        "id": oid,
        "account_id": account_id,
        "symbol": symbol,
        "instrument_type": instrument_type,
        "option_strategy": option_strategy,
        "side": side,
        "order_type": order_type,
        "quantity": quantity,
        "limit_price_cents": limit_price,
        "stop_price_cents": stop_price,
        "status": cfg.ORDER_ACCEPTED,
        "fill_price_cents": None,
        "filled_at": None,
        "opened_for_day_trade": False,
        "margin_requirement_cents": margin_req,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    with store.lock:
        store.orders[oid] = order

        if order_type == cfg.ORDER_TYPE_MARKET:
            # Auto-fill at reference price.
            order["status"] = cfg.ORDER_FILLED
            order["fill_price_cents"] = ref_price
            order["filled_at"] = now
            apply_fill_cash_adjustment(order, a, ref_price)
            recompute_equity(a)
            touch(a, now)
            # Day-trade pairing + PDT check.
            paired = pair_day_trade_if_any(order, now)
            touch(order, now)
            if paired is not None:
                evaluate_pdt(a, now)
        else:
            # Non-MARKET: ACCEPTED → WORKING immediately.
            order["status"] = cfg.ORDER_WORKING
            touch(order, now)

    return success(order_view(order), 201)


# ── GET /brokerage/orders/{id} ─────────────────────────────────────────────

@bp.get("/brokerage/orders/<order_id>")
@require_auth([cfg.ROLE_CUSTOMER, cfg.ROLE_COMPLIANCE, cfg.ROLE_ADMIN])
def get_order(order_id: str):
    o = get_order_or_404(order_id)
    if g.role == cfg.ROLE_CUSTOMER:
        a = store.accounts.get(o["account_id"])
        if a is None or a["customer_id"] != g.user_id:
            raise err_ownership()
    return success(order_view(o), 200)


# ── GET /brokerage/orders ──────────────────────────────────────────────────

@bp.get("/brokerage/orders")
@require_auth([cfg.ROLE_CUSTOMER, cfg.ROLE_COMPLIANCE, cfg.ROLE_ADMIN])
def list_orders():
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    symbol = request.args.get("symbol")
    status_f = request.args.get("status")

    rows = list(store.orders.values())
    if g.role == cfg.ROLE_CUSTOMER:
        # Filter to caller-owned accounts.
        owned = {a["id"] for a in store.accounts.values() if a["customer_id"] == g.user_id}
        rows = [r for r in rows if r["account_id"] in owned]
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    if symbol is not None:
        rows = [r for r in rows if r["symbol"] == symbol]
    if status_f is not None:
        rows = [r for r in rows if r["status"] == status_f]

    rows = sort_by_created_at(rows)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return list_success([order_view(r) for r in page], limit, offset, total)


# ── POST /brokerage/orders/{id}/fill ───────────────────────────────────────

@bp.post("/brokerage/orders/<order_id>/fill")
@require_auth([cfg.ROLE_ADMIN])
def fill_order(order_id: str):
    o = get_order_or_404(order_id)
    a = store.accounts.get(o["account_id"])
    if a is None:
        raise err_invalid_state("orphan order")

    if o["status"] != cfg.ORDER_WORKING:
        raise err_invalid_state("fill requires WORKING")

    body = get_json()
    exec_price = require_int(body, "execution_price_cents", minimum=1)

    # Price-semantics check (priority 24).
    ot = o["order_type"]
    side = o["side"]
    lp = o.get("limit_price_cents")
    sp = o.get("stop_price_cents")
    if ot == cfg.ORDER_TYPE_LIMIT:
        if side == cfg.SIDE_BUY and exec_price > lp:
            raise err_fill_price_violates_limits()
        if side == cfg.SIDE_SELL and exec_price < lp:
            raise err_fill_price_violates_limits()
    elif ot == cfg.ORDER_TYPE_STOP:
        if side == cfg.SIDE_BUY and exec_price < sp:
            raise err_fill_price_violates_limits()
        if side == cfg.SIDE_SELL and exec_price > sp:
            raise err_fill_price_violates_limits()
    elif ot == cfg.ORDER_TYPE_STOP_LIMIT:
        if side == cfg.SIDE_BUY:
            if exec_price < sp or exec_price > lp:
                raise err_fill_price_violates_limits()
        else:
            if exec_price > sp or exec_price < lp:
                raise err_fill_price_violates_limits()
    elif ot == cfg.ORDER_TYPE_TAKE_PROFIT:
        # Treat take-profit identically to LIMIT for fill semantics.
        if side == cfg.SIDE_BUY and exec_price > lp:
            raise err_fill_price_violates_limits()
        if side == cfg.SIDE_SELL and exec_price < lp:
            raise err_fill_price_violates_limits()

    now = store.now()
    with store.lock:
        o["status"] = cfg.ORDER_FILLED
        o["fill_price_cents"] = exec_price
        o["filled_at"] = now
        apply_fill_cash_adjustment(o, a, exec_price)
        recompute_equity(a)
        touch(a, now)
        paired = pair_day_trade_if_any(o, now)
        touch(o, now)
        if paired is not None:
            evaluate_pdt(a, now)
    return success(order_view(o), 200)


# ── DELETE /brokerage/orders/{id} ──────────────────────────────────────────

@bp.delete("/brokerage/orders/<order_id>")
@require_auth([cfg.ROLE_CUSTOMER])
def cancel_order(order_id: str):
    o = get_order_or_404(order_id)
    a = store.accounts.get(o["account_id"])
    if a is None or a["customer_id"] != g.user_id:
        raise err_ownership()

    if o["status"] not in cfg.ORDER_OPEN:
        raise err_invalid_state("cancel requires ACCEPTED or WORKING")

    now = store.now()
    with store.lock:
        o["status"] = cfg.ORDER_CANCELLED
        touch(o, now)
    return success(order_view(o), 200)
