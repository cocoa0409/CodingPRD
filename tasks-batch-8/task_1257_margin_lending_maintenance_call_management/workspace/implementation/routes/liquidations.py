"""Liquidation orders (PRD 3.9): server-side selector policy, segregated
create/fill hands, reservation compensation on cancel."""
from flask import Blueprint, request

from authz import ANY_ROLE, DESK, require_roles
from calc import (
    NON_TERMINAL_ORDER_STATES,
    recompute_account,
    select_liquidation_positions,
)
from cascades import (
    after_liquidation_cancel,
    after_liquidation_fill,
    non_terminal_orders_for_account,
    posture_recheck,
)
from db import store
from errors import (
    call_not_expired,
    fill_exceeds_quantity,
    invalid_request,
    liquidation_invalid_state,
    liquidation_in_progress,
    liquidation_order_not_found,
    no_liquidatable_positions,
    position_reserved,
    segregation_of_duties,
    stale_version,
)
from response import success
from serialize import ser_liquidation_order
from store_ops import (
    json_body,
    new_id,
    paginate,
    req_int,
    req_str,
    sorted_by_creation,
    stamp_new,
    touch,
)
from errors import call_not_found
from routes.accounts import get_account_or_404
from routes.calls import get_call_or_404

bp = Blueprint("liquidations", __name__)


def get_order_or_404(order_id):
    order = store.liquidation_orders.get(order_id)
    if order is None:
        raise liquidation_order_not_found()
    return order


@bp.route("/margin/accounts/<aid>/liquidation-orders", methods=["POST"])
def create_liquidation_orders(aid):
    data = json_body()
    call_id = req_str(data, "call_id")
    expected_version = req_int(data, "expected_account_version")
    uid, _ = require_roles([DESK])
    account = get_account_or_404(aid)
    call = get_call_or_404(call_id)
    if call["account_id"] != aid:
        # Scoped lookup: the call must belong to the addressed account.
        raise call_not_found("call does not belong to this account")
    # OCC on the parent account (PRD 2.8) — checked before state evaluation.
    if expected_version != account["version"]:
        raise stale_version()
    # The account-level liquidation lock fires before the call-state check:
    # while an earlier order is non-terminal, creation is rejected with
    # ERR_LIQUIDATION_IN_PROGRESS regardless of the call's state (PRD 3.9).
    if non_terminal_orders_for_account(aid):
        raise liquidation_in_progress()
    if call["call_status"] != "EXPIRED":
        raise call_not_expired()

    selected, eligible = select_liquidation_positions(account, call)
    if not eligible or not selected:
        raise no_liquidatable_positions()
    total = sum(abs(t[4]["mv_official_cents"]) for t in eligible)
    if total < call["call_amount_cents"]:
        raise no_liquidatable_positions()
    if any(p["reserved_qty"] != 0 for p in selected):
        raise position_reserved()

    # One order per selected position, created atomically in rank order.
    orders = []
    for p in selected:
        order = {
            "id": new_id(),
            "account_id": aid,
            "call_id": call_id,
            "position_id": p["id"],
            "quantity": abs(p["quantity"]),
            "filled_quantity": 0,
            "proceeds_cents": 0,
            "order_status": "PENDING",
            "created_by_user_id": uid,
            "last_filled_by_user_id": None,
        }
        stamp_new(order)
        store.liquidation_orders[order["id"]] = order
        p["reserved_qty"] += order["quantity"]
        touch(p)
        orders.append(order)

    call["call_status"] = "LIQUIDATION_IN_PROGRESS"
    touch(call)
    # A successful guarded write increments the account version by exactly one.
    touch(account)
    posture_recheck(account)
    # The response returns the first-ranked order.
    return success(ser_liquidation_order(orders[0]), status=201)


@bp.route("/margin/liquidation-orders/<oid>", methods=["GET"])
def get_liquidation_order(oid):
    require_roles(ANY_ROLE)
    return success(ser_liquidation_order(get_order_or_404(oid)))


@bp.route("/margin/liquidation-orders", methods=["GET"])
def list_liquidation_orders():
    require_roles(ANY_ROLE)
    account_id = request.args.get("account_id")
    call_id = request.args.get("call_id")
    position_id = request.args.get("position_id")
    items = list(store.liquidation_orders.values())
    if account_id is not None:
        items = [o for o in items if o["account_id"] == account_id]
    if call_id is not None:
        items = [o for o in items if o["call_id"] == call_id]
    if position_id is not None:
        items = [o for o in items if o["position_id"] == position_id]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_liquidation_order(o) for o in page], response_type="array",
                   pagination=pagination)


@bp.route("/margin/margin-calls/<cid>/liquidation-orders", methods=["GET"])
def list_call_liquidation_orders(cid):
    require_roles(ANY_ROLE)
    get_call_or_404(cid)
    items = sorted_by_creation(
        [o for o in store.liquidation_orders.values() if o["call_id"] == cid])
    page, pagination = paginate(items)
    return success([ser_liquidation_order(o) for o in page], response_type="array",
                   pagination=pagination)


@bp.route("/margin/liquidation-orders/<oid>/fill", methods=["POST"])
def fill_liquidation_order(oid):
    data = json_body()
    filled_quantity = req_int(data, "filled_quantity")
    fill_price = req_int(data, "fill_price_cents")
    if fill_price <= 0:
        raise invalid_request("Field fill_price_cents must be positive")
    uid, _ = require_roles([DESK])
    order = get_order_or_404(oid)
    # Pinned precondition order: state -> segregation -> fill quantity.
    if order["order_status"] not in NON_TERMINAL_ORDER_STATES:
        raise liquidation_invalid_state()
    if uid == order["created_by_user_id"]:
        raise segregation_of_duties()
    remaining = order["quantity"] - order["filled_quantity"]
    if filled_quantity <= 0 or filled_quantity > remaining:
        raise fill_exceeds_quantity()

    account = store.accounts[order["account_id"]]
    position = store.positions[order["position_id"]]
    fill_value = filled_quantity * fill_price

    # Reduce the position toward zero and release the filled reservation.
    if position["quantity"] > 0:
        position["quantity"] -= filled_quantity
        account["cash_balance_cents"] += fill_value  # selling a long credits
    else:
        position["quantity"] += filled_quantity
        account["cash_balance_cents"] -= fill_value  # buying to cover debits
    position["reserved_qty"] -= filled_quantity
    touch(position)

    order["filled_quantity"] += filled_quantity
    order["proceeds_cents"] += fill_value
    order["last_filled_by_user_id"] = uid
    order["order_status"] = ("EXECUTED" if order["filled_quantity"] == order["quantity"]
                             else "PARTIALLY_FILLED")
    touch(order)

    # Equity/requirements recompute on current marks; then the call cure test.
    recompute_account(account)
    touch(account)
    after_liquidation_fill(account, store.calls[order["call_id"]])
    return success(ser_liquidation_order(order))


@bp.route("/margin/liquidation-orders/<oid>/cancel", methods=["POST"])
def cancel_liquidation_order(oid):
    require_roles([DESK])
    order = get_order_or_404(oid)
    if order["order_status"] not in NON_TERMINAL_ORDER_STATES:
        raise liquidation_invalid_state()
    position = store.positions[order["position_id"]]
    # Compensation restores the reservation of the unfilled remainder; fills
    # already applied are not reversed.
    position["reserved_qty"] -= (order["quantity"] - order["filled_quantity"])
    touch(position)
    order["order_status"] = "CANCELLED"
    touch(order)
    account = store.accounts[order["account_id"]]
    after_liquidation_cancel(account, store.calls[order["call_id"]])
    return success(ser_liquidation_order(order))
