"""Trade-ins and buyback credit (PRD §3.6)."""
from flask import Blueprint, request

import db
from errors import ApiError
from middleware import get_caller, require_role, parse_pagination, paginate
from response import success
from services import serialize
from services.calc import metal_value_cents, buyback_credit_cents
from services.common import (
    get_body, require_str, require_int, require_enum, require_number, optional_number,
    resolve_fk, resolve_path, require_own_version, post_ledger_entry,
)

bp = Blueprint("trade_ins", __name__)

KARATS = {"K14", "K18", "K24"}
CONDITIONS = {"EXCELLENT", "GOOD", "FAIR"}


@bp.route("/trade-ins", methods=["POST"])
def create_trade_in():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager"})
    body = get_body()
    customer_id = require_str(body, "customer_id")
    resolve_fk(db.customers, customer_id)
    metal_karat = require_enum(body, "metal_karat", KARATS)
    metal_weight_grams = require_number(body, "metal_weight_grams", gt=0)
    spot_price = require_int(body, "metal_spot_price_cents_per_gram", gt=0)
    gemstone_value = optional_number(body, "gemstone_value_cents", default=0, ge=0)
    if isinstance(gemstone_value, float) and not gemstone_value.is_integer():
        raise ApiError("ERR_INVALID_REQUEST", "gemstone_value_cents must be an integer")
    gemstone_value = int(gemstone_value)
    condition = require_enum(body, "condition", CONDITIONS)
    mv = metal_value_cents(metal_weight_grams, spot_price, metal_karat)
    buyback = buyback_credit_cents(mv, gemstone_value, condition)
    rec = db.new_record()
    rec.update({
        "customer_id": customer_id, "metal_karat": metal_karat,
        "metal_weight_grams": metal_weight_grams,
        "metal_spot_price_cents_per_gram": spot_price,
        "gemstone_value_cents": gemstone_value, "condition": condition,
        "metal_value_cents": mv, "buyback_credit_cents": buyback,
        "credit_ledger_entry_id": None, "status": "OFFERED",
    })
    db.trade_ins[rec["id"]] = rec
    return success(serialize.trade_in(rec), status=201)


@bp.route("/trade-ins", methods=["GET"])
def list_trade_ins():
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    limit, offset = parse_pagination()
    f_customer = request.args.get("customer_id")
    f_ledger = request.args.get("credit_ledger_entry_id")
    records = []
    for t in db.trade_ins.values():
        if f_customer is not None and t["customer_id"] != f_customer:
            continue
        if f_ledger is not None and t.get("credit_ledger_entry_id") != f_ledger:
            continue
        records.append(t)
    page, meta = paginate(records, limit, offset)
    return success([serialize.trade_in(r) for r in page], status=200, pagination=meta)


@bp.route("/trade-ins/<tid>", methods=["GET"])
def get_trade_in(tid):
    _, role = get_caller()
    require_role(role, {"SalesAssociate", "StoreManager", "Customer"})
    rec = resolve_path(db.trade_ins, tid)
    return success(serialize.trade_in(rec), status=200)


@bp.route("/trade-ins/<tid>/accept", methods=["POST"])
def accept_trade_in(tid):
    _, role = get_caller()
    require_role(role, {"StoreManager"})
    rec = resolve_path(db.trade_ins, tid)
    body = get_body()
    if rec["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", "Offer is not OFFERED")
    customer = db.customers.get(rec["customer_id"])
    if customer is None or customer["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED", "Customer is not ACTIVE")
    require_own_version(rec, body)
    entry = post_ledger_entry(rec["customer_id"], "CREDIT", rec["buyback_credit_cents"], "TRADE_IN")
    rec["credit_ledger_entry_id"] = entry["id"]
    rec["status"] = "ACCEPTED"
    db.touch(rec)
    return success(serialize.trade_in(rec), status=200)


@bp.route("/trade-ins/<tid>/decline", methods=["POST"])
def decline_trade_in(tid):
    _, role = get_caller()
    require_role(role, {"StoreManager"})
    rec = resolve_path(db.trade_ins, tid)
    body = get_body()
    if rec["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", "Offer is not OFFERED")
    require_own_version(rec, body)
    rec["status"] = "DECLINED"
    db.touch(rec)
    return success(serialize.trade_in(rec), status=200)
