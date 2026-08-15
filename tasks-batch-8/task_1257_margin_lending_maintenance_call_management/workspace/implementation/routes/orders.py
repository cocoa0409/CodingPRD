"""Orders, positions, fills, day-trade events (PRD 3.4).

Market orders fill immediately, in full, at the security's latest REALTIME
mark. Opening orders (those that establish a position or grow its absolute
size) require ACTIVE posture, pass the PDT minimum-equity gate, need a
marginable security, and must satisfy the post-trade Reg T initial + house
requirement check in its pinned evaluation order.
"""
from flask import Blueprint, request

from authz import ANY_ROLE, CUSTOMER, check_customer_ownership, require_roles
from calc import (
    PDT_MIN_EQUITY_CENTS,
    account_position,
    compute_basis,
    latest_mark_price,
    recompute_account,
    reg_t_initial,
    round_half_up_div,
)
from cascades import record_day_trade_event
from db import store
from errors import (
    account_closed,
    account_restricted,
    day_trade_event_not_found,
    fill_not_found,
    insufficient_buying_power,
    no_market_mark,
    pdt_min_equity,
    position_not_found,
    security_not_marginable,
)
from response import success
from serialize import ser_day_trade_event, ser_fill, ser_position
from store_ops import (
    json_body,
    new_id,
    paginate,
    req_enum,
    req_positive_int,
    req_str,
    sorted_by_creation,
    stamp_ledger,
    stamp_new,
    touch,
)
from routes.accounts import get_account_or_404
from routes.securities import get_security_or_404

bp = Blueprint("orders", __name__)

SIDES = ("BUY", "SELL", "SELL_SHORT", "BUY_TO_COVER")
_BUYS = ("BUY", "BUY_TO_COVER")


def _apply_avg_cost(position, delta, price):
    """Average acquisition price per share of the current open quantity."""
    old_q = position["quantity"]
    new_q = old_q + delta
    if new_q == 0:
        return  # keep last average; quantity is flat
    if old_q == 0 or (old_q > 0) != (new_q > 0):
        # 0 -> non-zero, or a sign flip: the residual opens at this price.
        position["avg_cost_cents"] = price
        position["opened_at"] = store.clock
        return
    if abs(new_q) > abs(old_q):
        total = abs(old_q) * position["avg_cost_cents"] + abs(delta) * price
        position["avg_cost_cents"] = round_half_up_div(total, abs(new_q))
    # reductions keep the average


@bp.route("/margin/accounts/<aid>/orders", methods=["POST"])
def place_order(aid):
    data = json_body()
    security_id = req_str(data, "security_id")
    side = req_enum(data, "side", SIDES)
    quantity = req_positive_int(data, "quantity")
    uid, _ = require_roles([CUSTOMER])
    account = get_account_or_404(aid)
    security = get_security_or_404(security_id)
    check_customer_ownership(uid, account["customer_id"])

    if account["account_status"] == "CLOSED":
        raise account_closed()

    position = account_position(aid, security_id)
    old_q = 0 if position is None else position["quantity"]
    delta = quantity if side in _BUYS else -quantity
    new_q = old_q + delta
    # Opening = the fill establishes a position or grows its absolute size
    # (a cross through zero reopens a residual on the other side; an exact
    # close to zero is never opening).
    opening = abs(new_q) > abs(old_q) or (
        new_q != 0 and old_q != 0 and (old_q > 0) != (new_q > 0))

    # Priority 5: opening orders require ACTIVE posture.
    if opening and account["account_status"] == "RESTRICTED":
        raise account_restricted()
    # Priority 6: PDT minimum-equity gate on opening orders.
    if (opening and account["pdt_flag"]
            and account["equity_realtime_cents"] < PDT_MIN_EQUITY_CENTS):
        raise pdt_min_equity()
    # Priority 8: instrument structural rules.
    if opening and not security["marginable"]:
        raise security_not_marginable()
    price = latest_mark_price(security_id, "REALTIME")
    if price is None:
        raise no_market_mark()

    # Priority 10: post-trade buying power, pinned evaluation order (PRD 3.4):
    # cash' -> positions'/MV' -> equity' -> Reg T initial' -> house' (realtime).
    if opening:
        cash_after = account["cash_balance_cents"] + (-delta * price)
        hypo = {
            "id": account["id"],
            "cash_balance_cents": cash_after,
        }
        # Post-trade position set: same rows, this security's quantity updated.
        saved_qty = None if position is None else position["quantity"]
        saved_mv = None if position is None else position["mv_realtime_cents"]
        if position is None:
            position = {
                "id": "__hypo__", "account_id": aid, "security_id": security_id,
                "quantity": 0, "mv_realtime_cents": 0, "mv_official_cents": 0,
            }
            store.positions["__hypo__"] = position
        position["quantity"] = new_q
        position["mv_realtime_cents"] = new_q * price
        rt = compute_basis(hypo, "REALTIME")
        if saved_qty is None:
            del store.positions["__hypo__"]
            position = None
        else:
            position["quantity"] = saved_qty
            position["mv_realtime_cents"] = saved_mv
        initial_req = reg_t_initial(rt.gross_long, rt.gross_short)
        if rt.equity < initial_req or rt.equity < rt.house_req:
            raise insufficient_buying_power()

    # --- execute the fill atomically -------------------------------------
    if position is None:
        position = {
            "id": new_id(),
            "account_id": aid,
            "security_id": security_id,
            "quantity": 0,
            "avg_cost_cents": 0,
            "mv_realtime_cents": 0,
            "mv_official_cents": 0,
            "reserved_qty": 0,
            "opened_at": None,
            "today_bought_qty": 0,
            "today_sold_qty": 0,
            "last_trade_date": None,
        }
        stamp_new(position)
        store.positions[position["id"]] = position
        store.position_by_pair[(aid, security_id)] = position["id"]

    fill_date = store.clock.date()
    # Lazy day-counter reset on the first fill of a new date (PRD 3.4).
    if position["last_trade_date"] != fill_date:
        position["today_bought_qty"] = 0
        position["today_sold_qty"] = 0

    is_day_trade = False
    bought_before = position["today_bought_qty"]
    sold_before = position["today_sold_qty"]
    if side == "BUY":
        position["today_bought_qty"] = bought_before + quantity
    elif side == "SELL_SHORT":
        position["today_sold_qty"] = sold_before + quantity
    elif side == "SELL":
        # Closes long shares bought the same day (PRD 3.4).
        if min(bought_before, quantity) > 0:
            is_day_trade = True
    elif side == "BUY_TO_COVER":
        # Symmetric for shorts opened today.
        if min(sold_before, quantity) > 0:
            is_day_trade = True

    _apply_avg_cost(position, delta, price)
    position["quantity"] = new_q
    position["last_trade_date"] = fill_date
    position["mv_realtime_cents"] = new_q * price
    off_price = latest_mark_price(security_id, "OFFICIAL_CLOSE")
    position["mv_official_cents"] = new_q * (0 if off_price is None else off_price)
    touch(position)

    # Cash moves with the fill: BUY/BUY_TO_COVER debit, SELL/SELL_SHORT credit.
    account["cash_balance_cents"] += -delta * price

    fill = {
        "id": new_id(),
        "account_id": aid,
        "security_id": security_id,
        "side": side,
        "quantity": quantity,
        "price_cents": price,
        "fill_date": fill_date,
        "is_day_trade": is_day_trade,
    }
    stamp_ledger(fill)
    store.fills[fill["id"]] = fill

    if is_day_trade:
        record_day_trade_event(aid, security_id, fill_date)

    # Every fill recomputes the account on both bases (one mutation).
    recompute_account(account)
    touch(account)
    return success(ser_position(position), status=201)


# --- positions ---------------------------------------------------------------
@bp.route("/margin/accounts/<aid>/positions", methods=["GET"])
def list_account_positions(aid):
    require_roles(ANY_ROLE)
    get_account_or_404(aid)
    items = sorted_by_creation(
        [p for p in store.positions.values() if p["account_id"] == aid])
    page, pagination = paginate(items)
    return success([ser_position(p) for p in page], response_type="array",
                   pagination=pagination)


@bp.route("/margin/positions/<pid>", methods=["GET"])
def get_position(pid):
    require_roles(ANY_ROLE)
    position = store.positions.get(pid)
    if position is None:
        raise position_not_found()
    return success(ser_position(position))


@bp.route("/margin/positions", methods=["GET"])
def list_positions():
    require_roles(ANY_ROLE)
    account_id = request.args.get("account_id")
    security_id = request.args.get("security_id")
    items = list(store.positions.values())
    if account_id is not None:
        items = [p for p in items if p["account_id"] == account_id]
    if security_id is not None:
        items = [p for p in items if p["security_id"] == security_id]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_position(p) for p in page], response_type="array",
                   pagination=pagination)


# --- fills ---------------------------------------------------------------------
@bp.route("/margin/accounts/<aid>/fills", methods=["GET"])
def list_account_fills(aid):
    require_roles(ANY_ROLE)
    get_account_or_404(aid)
    items = sorted_by_creation(
        [f for f in store.fills.values() if f["account_id"] == aid])
    page, pagination = paginate(items)
    return success([ser_fill(f) for f in page], response_type="array",
                   pagination=pagination)


@bp.route("/margin/fills/<fid>", methods=["GET"])
def get_fill(fid):
    require_roles(ANY_ROLE)
    fill = store.fills.get(fid)
    if fill is None:
        raise fill_not_found()
    return success(ser_fill(fill))


@bp.route("/margin/fills", methods=["GET"])
def list_fills():
    require_roles(ANY_ROLE)
    account_id = request.args.get("account_id")
    security_id = request.args.get("security_id")
    items = list(store.fills.values())
    if account_id is not None:
        items = [f for f in items if f["account_id"] == account_id]
    if security_id is not None:
        items = [f for f in items if f["security_id"] == security_id]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_fill(f) for f in page], response_type="array",
                   pagination=pagination)


# --- day-trade events ------------------------------------------------------------
@bp.route("/margin/accounts/<aid>/day-trade-events", methods=["GET"])
def list_account_day_trade_events(aid):
    require_roles(ANY_ROLE)
    get_account_or_404(aid)
    items = sorted_by_creation(
        [e for e in store.day_trade_events.values() if e["account_id"] == aid])
    page, pagination = paginate(items)
    return success([ser_day_trade_event(e) for e in page], response_type="array",
                   pagination=pagination)


@bp.route("/margin/day-trade-events/<eid>", methods=["GET"])
def get_day_trade_event(eid):
    require_roles(ANY_ROLE)
    event = store.day_trade_events.get(eid)
    if event is None:
        raise day_trade_event_not_found()
    return success(ser_day_trade_event(event))


@bp.route("/margin/day-trade-events", methods=["GET"])
def list_day_trade_events():
    require_roles(ANY_ROLE)
    account_id = request.args.get("account_id")
    security_id = request.args.get("security_id")
    items = list(store.day_trade_events.values())
    if account_id is not None:
        items = [e for e in items if e["account_id"] == account_id]
    if security_id is not None:
        items = [e for e in items if e["security_id"] == security_id]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_day_trade_event(e) for e in page], response_type="array",
                   pagination=pagination)
