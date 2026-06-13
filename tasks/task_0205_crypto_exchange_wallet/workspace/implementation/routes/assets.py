"""Asset config and fee schedule (§3.3)."""
from flask import Blueprint, request

from auth import get_identity, require_roles
from db import db, new_id, next_seq
from errors import err
from response import success
from serializers import asset_out, fee_schedule_out
from services.common import (
    require_body, required_str, required_int, required_number, required_enum, touch,
)
from services.pagination import paginate
from numeric import D

bp = Blueprint("assets", __name__)

FEE_TIERS = {"TIER_BASE", "TIER_1", "TIER_2", "TIER_3"}


def get_asset_or_404(asset_id):
    a = db.assets.get(asset_id)
    if a is None:
        raise err("ERR_NOT_FOUND", "Asset not found")
    return a


@bp.route("/assets", methods=["POST"])
def create_asset():
    user_id, role = get_identity()
    require_roles(role, {"Operator"})
    body = require_body(request.get_json(silent=True))
    symbol = required_str(body, "symbol")
    decimals = required_int(body, "decimals")
    required_confirmations = required_int(body, "required_confirmations")
    is_fiat = body.get("is_fiat", False)
    if is_fiat is None:
        is_fiat = False
    if not isinstance(is_fiat, bool):
        raise err("ERR_INVALID_REQUEST", "is_fiat must be a boolean")
    min_withdrawal_amount = required_number(body, "min_withdrawal_amount")
    network_fee = required_number(body, "network_fee")
    spot_price_usd = required_number(body, "spot_price_usd")

    if db.asset_by_symbol(symbol) is not None:
        raise err("ERR_INVALID_REQUEST", "symbol already exists")

    now = db.clock.now()
    a = {
        "id": new_id(),
        "symbol": symbol,
        "decimals": decimals,
        "required_confirmations": required_confirmations,
        "is_fiat": is_fiat,
        "min_withdrawal_amount": min_withdrawal_amount,
        "network_fee": network_fee,
        "spot_price_usd": spot_price_usd,
        "created_at": now,
        "_seq": next_seq(),
    }
    db.assets[a["id"]] = a
    return success(asset_out(a), status=201)


@bp.route("/assets/<asset_id>", methods=["GET"])
def get_asset(asset_id):
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator", "ComplianceOfficer"})
    a = get_asset_or_404(asset_id)
    return success(asset_out(a))


@bp.route("/assets/<asset_id>", methods=["PATCH"])
def patch_asset(asset_id):
    user_id, role = get_identity()
    require_roles(role, {"Operator"})
    a = get_asset_or_404(asset_id)
    body = require_body(request.get_json(silent=True))
    spot = required_number(body, "spot_price_usd")
    a["spot_price_usd"] = spot
    # AssetConfig carries only id/created_at; no version/updated_at.
    return success(asset_out(a))


@bp.route("/fee-schedules", methods=["POST"])
def create_fee_schedule():
    user_id, role = get_identity()
    require_roles(role, {"Operator"})
    body = require_body(request.get_json(silent=True))
    tier_name = required_enum(body, "tier_name", FEE_TIERS)
    min_vol = required_number(body, "min_taker_volume_30d_usd")
    maker_bps = required_number(body, "maker_fee_bps")
    taker_bps = required_number(body, "taker_fee_bps")
    if db.fee_schedule_by_tier(tier_name) is not None:
        raise err("ERR_INVALID_REQUEST", "tier_name already exists")
    now = db.clock.now()
    f = {
        "id": new_id(),
        "tier_name": tier_name,
        "min_taker_volume_30d_usd": min_vol,
        "maker_fee_bps": maker_bps,
        "taker_fee_bps": taker_bps,
        "created_at": now,
        "_seq": next_seq(),
    }
    db.fee_schedules[f["id"]] = f
    return success(fee_schedule_out(f), status=201)


@bp.route("/fee-schedules", methods=["GET"])
def list_fee_schedules():
    user_id, role = get_identity()
    require_roles(role, {"Trader", "Operator"})
    items = sorted(db.fee_schedules.values(), key=lambda f: (f["created_at"], f["_seq"]))
    page, pag = paginate(items)
    return success([fee_schedule_out(f) for f in page], pagination=pag)
