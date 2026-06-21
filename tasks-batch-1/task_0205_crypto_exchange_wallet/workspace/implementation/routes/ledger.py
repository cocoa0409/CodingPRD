"""Balances, cost-basis lots, and the test-driving clock (§2.6, §3.10, §2.4)."""
from flask import Blueprint, request

from auth import get_identity, require_roles
from clock import parse_iso8601
from db import db
from errors import err
from response import success
from serializers import balance_out, cost_basis_lot_out
from services.common import require_body
from services.pagination import paginate

bp = Blueprint("ledger", __name__)


@bp.route("/balances", methods=["GET"])
def list_balances():
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator"})
    items = list(db.balances.values())
    acct = request.args.get("account_id")
    if acct is not None:
        items = [b for b in items if b["account_id"] == acct]
    asset = request.args.get("asset")
    if asset is not None:
        items = [b for b in items if b["asset"] == asset]
    items.sort(key=lambda b: (b["created_at"], b["_seq"]))
    page, pag = paginate(items)
    return success([balance_out(b) for b in page], pagination=pag)


@bp.route("/balances/<bid>", methods=["GET"])
def get_balance(bid):
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator"})
    b = db.balances.get(bid)
    if b is None:
        raise err("ERR_NOT_FOUND", "Balance not found")
    return success(balance_out(b))


@bp.route("/cost-basis-lots", methods=["GET"])
def list_lots():
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator"})
    items = list(db.cost_basis_lots.values())
    acct = request.args.get("account_id")
    if acct is not None:
        items = [l for l in items if l["account_id"] == acct]
    asset = request.args.get("asset")
    if asset is not None:
        items = [l for l in items if l["asset"] == asset]
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    items.sort(key=lambda l: (l["created_at"], l["_seq"]))
    page, pag = paginate(items)
    return success([cost_basis_lot_out(l) for l in page], pagination=pag)


@bp.route("/cost-basis-lots/<lid>", methods=["GET"])
def get_lot(lid):
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator"})
    l = db.cost_basis_lots.get(lid)
    if l is None:
        raise err("ERR_NOT_FOUND", "Cost-basis lot not found")
    return success(cost_basis_lot_out(l))


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = get_identity()
    require_roles(role, {"Operator"})
    body = require_body(request.get_json(silent=True))
    raw = body.get("to_iso8601")
    if not isinstance(raw, str) or raw == "":
        raise err("ERR_INVALID_REQUEST", "Missing required field: to_iso8601")
    try:
        dt = parse_iso8601(raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO-8601 instant")
    db.clock.set(dt)
    return success({}, status=200)
