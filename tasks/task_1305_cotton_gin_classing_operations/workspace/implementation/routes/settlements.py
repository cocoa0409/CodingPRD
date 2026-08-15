"""Settlement transition routes (finalize / pay / get)."""

from flask import Blueprint

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_SETTLEMENT_NOT_FOUND,
    ERR_SETTLEMENT_NOT_FINALIZABLE,
    ERR_SETTLEMENT_NOT_FINAL,
    ERR_UNGINNED_MODULES_EXIST,
    ERR_UNCLASSED_BALES_EXIST,
    ERR_UNSOLD_SEED_EXISTS,
    ERR_OVERPAYMENT,
)
from middleware import get_context, require_role, grower_owns, get_json_body, require_fields
from response import success_object
from services.core import touch, post_ledger
from services.calc import compute_settlement_lines
from routes.growers import _settlement_out

bp = Blueprint("settlements", __name__)


@bp.route("/gin-ops/settlements/<sid>", methods=["GET"])
def get_settlement(sid):
    user_id, role = get_context()
    s = db.settlements.get(sid)
    if s is None:
        err_id, status = ERR_SETTLEMENT_NOT_FOUND
        raise ApiError(err_id, "Settlement not found", status)
    grower_owns(user_id, role, s["grower_id"])
    return success_object(_settlement_out(s))


@bp.route("/gin-ops/settlements/<sid>/finalize", methods=["POST"])
def finalize_settlement(sid):
    user_id, role = get_context()
    require_role(role, {"CoopAccountant"})
    s = db.settlements.get(sid)
    if s is None:
        err_id, status = ERR_SETTLEMENT_NOT_FOUND
        raise ApiError(err_id, "Settlement not found", status)
    if s["status"] != "DRAFT":
        err_id, status = ERR_SETTLEMENT_NOT_FINALIZABLE
        raise ApiError(err_id, "Settlement is not DRAFT", status)
    gid = s["grower_id"]
    season = s["season"]
    # Gate 1: every module of (grower, season) must be GINNED or REJECTED
    modules = [
        m for m in db.modules.values()
        if m["grower_id"] == gid and m["season"] == season
    ]
    for m in modules:
        if m["status"] not in ("GINNED", "REJECTED"):
            err_id, status = ERR_UNGINNED_MODULES_EXIST
            raise ApiError(err_id, "Unginned modules exist for this grower-season", status)
    module_ids = {m["id"] for m in modules}
    # Gate 2: every bale of (grower, season) must be CLASSED
    for b in db.bales.values():
        if b["module_id"] in module_ids and b["classing_status"] != "CLASSED":
            err_id, status = ERR_UNCLASSED_BALES_EXIST
            raise ApiError(err_id, "Unclassed bales exist for this grower-season", status)
    # Gate 3: every shift holding a GINNED module of (grower, season) must have a SeedSale
    shift_ids = {
        m.get("gin_shift_id") for m in modules
        if m["status"] == "GINNED" and m.get("gin_shift_id")
    }
    for shift_id in shift_ids:
        has_sale = any(sale["gin_shift_id"] == shift_id for sale in db.seed_sales.values())
        if not has_sale:
            err_id, status = ERR_UNSOLD_SEED_EXISTS
            raise ApiError(err_id, "A reconciled shift holding ginned modules has no seed sale", status)
    grower = db.growers[gid]
    lines = compute_settlement_lines(grower, season, "FINAL")
    s.update(lines)
    s["computation_variant"] = "FINAL"
    s["status"] = "FINAL"
    touch(s)
    return success_object(_settlement_out(s))


@bp.route("/gin-ops/settlements/<sid>/pay", methods=["POST"])
def pay_settlement(sid):
    user_id, role = get_context()
    require_role(role, {"CoopAccountant"})
    s = db.settlements.get(sid)
    if s is None:
        err_id, status = ERR_SETTLEMENT_NOT_FOUND
        raise ApiError(err_id, "Settlement not found", status)
    body = get_json_body()
    require_fields(body, ["amount_cents"])
    amount = body["amount_cents"]
    if isinstance(amount, bool) or not isinstance(amount, int):
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "amount_cents must be an integer", status)
    if s["status"] != "FINAL":
        err_id, status = ERR_SETTLEMENT_NOT_FINAL
        raise ApiError(err_id, "Settlement is not FINAL", status)
    if amount != s["net_payable_cents"]:
        err_id, status = ERR_OVERPAYMENT
        raise ApiError(err_id, "amount_cents must equal net_payable_cents exactly", status)
    s["paid_amount_cents"] = amount
    s["status"] = "PAID"
    touch(s)
    gid = s["grower_id"]
    season = s["season"]
    post_ledger(gid, season, "PATRONAGE", s["patronage_cents"], f"settlement {sid}", settlement_id=sid)
    post_ledger(gid, season, "SETTLEMENT_PAYMENT", -s["net_payable_cents"], f"settlement {sid}", settlement_id=sid)
    return success_object(_settlement_out(s))
