"""Staking positions: stake, accrue, claim, unbond, release (§3.11)."""
from datetime import timedelta

from flask import Blueprint, request

from auth import get_identity, require_roles
from db import db, new_id, next_seq
from errors import err
from response import success
from serializers import staking_position_out
from services.common import (
    require_body, required_str, required_number, touch,
    available, credit_available, debit_available, credit_held, debit_held,
)
from services.cost_basis import create_lot
from services.pagination import paginate
from numeric import D, round_half_up

bp = Blueprint("staking", __name__)

YEAR_SECONDS = D("31536000")
UNBOND_COOLDOWN_DAYS = 7


def get_position_or_404(pid):
    p = db.staking_positions.get(pid)
    if p is None:
        raise err("ERR_NOT_FOUND", "Staking position not found")
    return p


def _accrue(position, asset_decimals):
    """Bring accrued_rewards current up to the clock. Returns the new accrued total."""
    now = db.clock.now()
    elapsed = (now - position["last_accrual_at"]).total_seconds()
    if elapsed < 0:
        elapsed = 0
    delta = (D(position["principal_amount"]) * (D(position["apr_bps"]) / D(10000))
             * (D(elapsed) / YEAR_SECONDS))
    delta = round_half_up(delta, asset_decimals)
    position["accrued_rewards"] = D(position["accrued_rewards"]) + delta
    return position["accrued_rewards"]


@bp.route("/staking-positions", methods=["POST"])
def stake():
    user_id, role = get_identity()
    require_roles(role, {"Trader"})
    body = require_body(request.get_json(silent=True))
    account_id = required_str(body, "account_id")
    asset = required_str(body, "asset")
    principal = required_number(body, "principal_amount", allow_zero=False)
    apr_bps = required_number(body, "apr_bps")

    acct = db.accounts.get(account_id)
    if acct is None:
        raise err("ERR_NOT_FOUND", "Account not found")
    if user_id != acct["id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Trader does not own this account")
    asset_cfg = db.asset_by_symbol(asset)
    if asset_cfg is None:
        raise err("ERR_NOT_FOUND", "Asset not found")

    if acct["account_status"] != "ACTIVE":
        raise err("ERR_ACCOUNT_FROZEN", "Account is frozen")

    # Cooldown overlap (closed interval, both endpoints inclusive).
    now = db.clock.now()
    for p in db.staking_positions.values():
        if (p["account_id"] == account_id and p["asset"] == asset
                and p["status"] == "UNBONDING"
                and p.get("unbond_started_at") and p.get("unbond_available_at")):
            if p["unbond_started_at"] <= now <= p["unbond_available_at"]:
                raise err("ERR_STAKE_COOLDOWN_OVERLAP", "An unbonding cooldown overlaps")

    bal = db.get_or_create_balance(account_id, asset)
    if available(bal) < principal:
        raise err("ERR_INSUFFICIENT_AVAILABLE", "Insufficient available to stake")

    debit_available(bal, principal)
    credit_held(bal, principal)
    p = {
        "id": new_id(),
        "account_id": account_id,
        "asset": asset,
        "principal_amount": principal,
        "apr_bps": apr_bps,
        "accrued_rewards": D(0),
        "last_accrual_at": now,
        "status": "ACTIVE",
        "unbond_started_at": None,
        "unbond_available_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db.staking_positions[p["id"]] = p
    return success(staking_position_out(p), status=201)


@bp.route("/staking-positions", methods=["GET"])
def list_positions():
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator"})
    items = list(db.staking_positions.values())
    for key in ("account_id", "asset", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if p.get(key) == val]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    page, pag = paginate(items)
    return success([staking_position_out(p) for p in page], pagination=pag)


@bp.route("/staking-positions/<pid>", methods=["GET"])
def get_position(pid):
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator"})
    p = get_position_or_404(pid)
    return success(staking_position_out(p))


@bp.route("/staking-positions/<pid>/claim", methods=["POST"])
def claim(pid):
    user_id, role = get_identity()
    require_roles(role, {"Trader"})
    p = get_position_or_404(pid)
    if user_id != p["account_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Trader does not own this position")
    if p["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Position is not ACTIVE")
    asset_cfg = db.asset_by_symbol(p["asset"])
    decimals = asset_cfg["decimals"]
    accrued = _accrue(p, decimals)
    if accrued <= 0:
        raise err("ERR_NOTHING_TO_CLAIM", "Nothing to claim")
    bal = db.get_or_create_balance(p["account_id"], p["asset"])
    credit_available(bal, accrued)
    create_lot(p["account_id"], p["asset"], "STAKING_REWARD", p["id"],
               accrued, D(asset_cfg["spot_price_usd"]), db.clock.now(), decimals)
    p["accrued_rewards"] = D(0)
    p["last_accrual_at"] = db.clock.now()
    touch(p)
    return success(staking_position_out(p))


@bp.route("/staking-positions/<pid>/unbond", methods=["POST"])
def unbond(pid):
    user_id, role = get_identity()
    require_roles(role, {"Trader"})
    p = get_position_or_404(pid)
    if user_id != p["account_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Trader does not own this position")
    if p["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Position is not ACTIVE")
    asset_cfg = db.asset_by_symbol(p["asset"])
    decimals = asset_cfg["decimals"]
    accrued = _accrue(p, decimals)
    if accrued > 0:
        bal = db.get_or_create_balance(p["account_id"], p["asset"])
        credit_available(bal, accrued)
        create_lot(p["account_id"], p["asset"], "STAKING_REWARD", p["id"],
                   accrued, D(asset_cfg["spot_price_usd"]), db.clock.now(), decimals)
        p["accrued_rewards"] = D(0)
    p["last_accrual_at"] = db.clock.now()
    now = db.clock.now()
    p["status"] = "UNBONDING"
    p["unbond_started_at"] = now
    p["unbond_available_at"] = now + timedelta(days=UNBOND_COOLDOWN_DAYS)
    touch(p)
    return success(staking_position_out(p))


@bp.route("/staking-positions/<pid>/release", methods=["POST"])
def release(pid):
    user_id, role = get_identity()
    require_roles(role, {"Trader"})
    p = get_position_or_404(pid)
    if user_id != p["account_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Trader does not own this position")
    if p["status"] != "UNBONDING":
        raise err("ERR_INVALID_STATE", "Position is not UNBONDING")
    if db.clock.now() < p["unbond_available_at"]:
        raise err("ERR_NOTHING_TO_CLAIM", "Cooldown has not elapsed")
    bal = db.get_or_create_balance(p["account_id"], p["asset"])
    debit_held(bal, D(p["principal_amount"]))
    credit_available(bal, D(p["principal_amount"]))
    p["status"] = "CLOSED"
    touch(p)
    return success(staking_position_out(p))
