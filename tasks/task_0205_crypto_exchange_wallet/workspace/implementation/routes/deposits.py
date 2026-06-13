"""Deposits and confirmation hold (§3.4)."""
from flask import Blueprint, request

from auth import get_identity, require_roles
from db import db, new_id, next_seq
from errors import err
from response import success
from serializers import deposit_out
from services.common import (
    require_body, required_str, required_number, required_int, touch,
    credit_held, debit_held, credit_available,
)
from services.cost_basis import create_lot
from services.pagination import paginate
from numeric import D

bp = Blueprint("deposits", __name__)


def get_deposit_or_404(dep_id):
    d = db.deposits.get(dep_id)
    if d is None:
        raise err("ERR_NOT_FOUND", "Deposit not found")
    return d


@bp.route("/deposits", methods=["POST"])
def create_deposit():
    user_id, role = get_identity()
    require_roles(role, {"Operator"})
    body = require_body(request.get_json(silent=True))
    account_id = required_str(body, "account_id")
    asset = required_str(body, "asset")
    amount = required_number(body, "amount", allow_zero=False)
    unit_cost = required_number(body, "unit_cost_usd")

    if account_id not in db.accounts:
        raise err("ERR_NOT_FOUND", "Account not found")
    if db.asset_by_symbol(asset) is None:
        raise err("ERR_NOT_FOUND", "Asset not found")

    now = db.clock.now()
    d = {
        "id": new_id(),
        "account_id": account_id,
        "asset": asset,
        "amount": amount,
        "confirmations": 0,
        "unit_cost_usd": unit_cost,
        "status": "DETECTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db.deposits[d["id"]] = d
    return success(deposit_out(d), status=201)


@bp.route("/deposits", methods=["GET"])
def list_deposits():
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator"})
    items = list(db.deposits.values())
    acct = request.args.get("account_id")
    if acct is not None:
        items = [d for d in items if d["account_id"] == acct]
    asset = request.args.get("asset")
    if asset is not None:
        items = [d for d in items if d["asset"] == asset]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items.sort(key=lambda d: (d["created_at"], d["_seq"]))
    page, pag = paginate(items)
    return success([deposit_out(d) for d in page], pagination=pag)


@bp.route("/deposits/<dep_id>", methods=["GET"])
def get_deposit(dep_id):
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator"})
    d = get_deposit_or_404(dep_id)
    return success(deposit_out(d))


@bp.route("/deposits/<dep_id>/confirmations", methods=["POST"])
def confirm_deposit(dep_id):
    user_id, role = get_identity()
    require_roles(role, {"Operator"})
    d = get_deposit_or_404(dep_id)
    body = require_body(request.get_json(silent=True))
    delta = required_int(body, "delta")

    asset_cfg = db.asset_by_symbol(d["asset"])
    if asset_cfg is None:
        raise err("ERR_NOT_FOUND", "Asset not found")
    required = asset_cfg["required_confirmations"]
    is_fiat = asset_cfg["is_fiat"]
    decimals = asset_cfg["decimals"]

    status = d["status"]
    if status not in ("DETECTED", "CONFIRMING"):
        raise err("ERR_INVALID_STATE", "Deposit not in a confirmable state")

    bal = db.get_or_create_balance(d["account_id"], d["asset"])

    if status == "DETECTED" and is_fiat:
        # Fiat instant credit: DETECTED -> CREDITED.
        d["confirmations"] = d["confirmations"] + delta
        d["status"] = "CREDITED"
        credit_available(bal, d["amount"])
        create_lot(d["account_id"], d["asset"], "DEPOSIT", d["id"],
                   d["amount"], d["unit_cost_usd"], db.clock.now(), decimals)
        touch(d)
        return success(deposit_out(d))

    if status == "DETECTED":
        # Non-fiat first advance lands in CONFIRMING and credits held; the state
        # machine has no DETECTED->CREDITED transition for non-fiat assets, so a
        # CREDITED crossing requires a later advance from CONFIRMING.
        d["confirmations"] = d["confirmations"] + delta
        d["status"] = "CONFIRMING"
        credit_held(bal, d["amount"])
        touch(d)
        return success(deposit_out(d))

    # status == CONFIRMING
    new_count = d["confirmations"] + delta
    if new_count >= required:
        d["confirmations"] = new_count
        debit_held(bal, d["amount"])
        credit_available(bal, d["amount"])
        d["status"] = "CREDITED"
        create_lot(d["account_id"], d["asset"], "DEPOSIT", d["id"],
                   d["amount"], d["unit_cost_usd"], db.clock.now(), decimals)
    else:
        d["confirmations"] = new_count
    touch(d)
    return success(deposit_out(d))


@bp.route("/deposits/<dep_id>/orphan", methods=["POST"])
def orphan_deposit(dep_id):
    user_id, role = get_identity()
    require_roles(role, {"Operator"})
    d = get_deposit_or_404(dep_id)
    if d["status"] != "DETECTED":
        raise err("ERR_INVALID_STATE", "Only DETECTED deposits may be orphaned")
    d["status"] = "ORPHANED"
    touch(d)
    return success(deposit_out(d))
