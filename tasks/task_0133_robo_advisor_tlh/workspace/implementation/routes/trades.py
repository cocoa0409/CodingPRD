"""Trade endpoints."""
from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g, request

from db import store
from errors import (
    err_auth_forbidden,
    err_fk_not_found,
    err_insufficient_lot_shares,
    err_invalid_state,
    err_resource_not_found,
)
from middleware import require_auth
from response import list_success, success
from routes._helpers import (
    check_version,
    get_json,
    paginate,
    parse_pagination,
    parse_version,
    sort_by_created_at,
)
from routes.accounts import (
    enforce_account_active,
    enforce_account_visible_to_caller,
    get_account_or_404,
)
from services.engine import (
    cancel_trade,
    execute_trade,
    settle_trade,
    stamp_create,
)
from services.serializers import serialize_trade
from utils import parse_iso

bp = Blueprint("trades", __name__)


def _get_trade_under_account_or_404(account_id, trade_id):
    t = store.trades.get(trade_id)
    if not t or t["account_id"] != account_id:
        raise err_resource_not_found("Trade not found under this account.")
    return t


# ── POST /accounts/{accountId}/trades  (create PENDING) ────────────────────


@bp.post("/accounts/<account_id>/trades")
@require_auth(["Advisor", "ClientUser"])
def create_trade(account_id):
    a = get_account_or_404(account_id)
    enforce_account_visible_to_caller(a)
    enforce_account_active(a)
    body = get_json()
    sid = body.get("security_id")
    side = body.get("side")
    requested_shares = body.get("requested_shares")
    if side not in ("BUY", "SELL"):
        raise err_invalid_state("side must be BUY or SELL.")
    if not isinstance(sid, str) or sid not in store.securities:
        raise err_fk_not_found("security_id not found.")
    if requested_shares is None or isinstance(requested_shares, bool) or not isinstance(requested_shares, (int, float)):
        raise err_invalid_state("requested_shares must be a positive number.")
    if requested_shares <= 0:
        raise err_invalid_state("requested_shares must be > 0.")
    cost_basis_method = body.get("cost_basis_method")
    specific_lot_id = body.get("specific_lot_id")
    if side == "SELL":
        if cost_basis_method is None:
            cost_basis_method = "FIFO"
        if cost_basis_method not in ("FIFO", "SPECIFIC_LOT"):
            raise err_invalid_state("cost_basis_method must be FIFO or SPECIFIC_LOT.")
        if cost_basis_method == "SPECIFIC_LOT":
            if not specific_lot_id:
                raise err_insufficient_lot_shares("specific_lot_id is required.")
            lot = store.lots.get(specific_lot_id)
            if not lot:
                raise err_insufficient_lot_shares("specific_lot_id does not resolve.")
            position = store.positions.get(lot["position_id"])
            if not position or position["account_id"] != account_id or position["security_id"] != sid:
                raise err_insufficient_lot_shares()
            if Decimal(str(lot["shares_remaining"])) < Decimal(str(requested_shares)):
                raise err_insufficient_lot_shares()
    else:
        cost_basis_method = None
        specific_lot_id = None

    with store.lock:
        trade = {
            "account_id": account_id,
            "security_id": sid,
            "side": side,
            "requested_shares": requested_shares,
            "cost_basis_method": cost_basis_method,
            "specific_lot_id": specific_lot_id,
            "rebalance_run_id": None,
            "status": "PENDING",
            "executed_at": None,
            "execution_price_cents": None,
            "gross_proceeds_cents": None,
            "realized_gain_loss_cents": None,
            "disallowed_loss_cents": 0,
        }
        stamp_create(trade)
        store.trades[trade["id"]] = trade
    return success(serialize_trade(trade), 201)


@bp.post("/accounts/<account_id>/trades/<trade_id>/execute")
@require_auth(["Advisor", "system"])
def execute_trade_endpoint(account_id, trade_id):
    a = get_account_or_404(account_id)
    enforce_account_active(a)
    t = _get_trade_under_account_or_404(account_id, trade_id)
    with store.lock:
        execute_trade(a, t)
    return success(serialize_trade(t))


@bp.post("/accounts/<account_id>/trades/<trade_id>/settle")
@require_auth(["Advisor", "system"])
def settle_trade_endpoint(account_id, trade_id):
    a = get_account_or_404(account_id)
    enforce_account_active(a)
    t = _get_trade_under_account_or_404(account_id, trade_id)
    with store.lock:
        settle_trade(a, t)
    return success(serialize_trade(t))


@bp.post("/accounts/<account_id>/trades/<trade_id>/cancel")
@require_auth(["Advisor", "ClientUser"])
def cancel_trade_endpoint(account_id, trade_id):
    a = get_account_or_404(account_id)
    enforce_account_visible_to_caller(a)
    enforce_account_active(a)
    t = _get_trade_under_account_or_404(account_id, trade_id)
    body = get_json()
    expected_version = parse_version(body)
    check_version(t, expected_version)
    with store.lock:
        cancel_trade(a, t)
    return success(serialize_trade(t))


@bp.get("/accounts/<account_id>/trades")
@require_auth(["Advisor", "ComplianceOfficer", "ClientUser", "TaxAdmin"])
def list_trades(account_id):
    a = get_account_or_404(account_id)
    if g.role == "ClientUser" and a["client_id"] != g.user_id:
        raise err_auth_forbidden("ClientUser may only view their own trades.")
    limit, offset = parse_pagination()
    status_filter = request.args.get("status")
    side_filter = request.args.get("side")
    year_filter = request.args.get("year")
    items = [t for t in store.trades.values() if t["account_id"] == account_id]
    if status_filter:
        items = [t for t in items if t["status"] == status_filter]
    if side_filter:
        items = [t for t in items if t["side"] == side_filter]
    if year_filter:
        try:
            y = int(year_filter)
            items = [
                t for t in items
                if t.get("executed_at") and parse_iso(t["executed_at"]).year == y
            ]
        except (TypeError, ValueError):
            items = []
    items = sort_by_created_at(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return list_success(
        [serialize_trade(t) for t in page], limit, offset, total
    )
