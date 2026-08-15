"""SeedSale routes."""

from flask import Blueprint

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_GIN_SHIFT_NOT_FOUND,
    ERR_SHIFT_NOT_RECONCILED,
    ERR_SHIFT_ALREADY_SOLD,
)
from middleware import get_context, require_role, get_json_body, require_fields
from response import success_object
from services.core import stamp_new, post_ledger
from services.calc import allocate_seed_pool, recompute_draft_settlements

bp = Blueprint("seed_sales", __name__)


def seed_sale_out(s):
    return {
        "id": s["id"],
        "gin_shift_id": s["gin_shift_id"],
        "buyer_name": s["buyer_name"],
        "price_cents_per_lb": s["price_cents_per_lb"],
        "sold_lbs": s["sold_lbs"],
        "net_pool_cents": s["net_pool_cents"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.route("/gin-ops/seed-sales", methods=["POST"])
def create_seed_sale():
    user_id, role = get_context()
    require_role(role, {"CoopAccountant"})
    body = get_json_body()
    require_fields(body, ["gin_shift_id", "buyer_name", "price_cents_per_lb"])
    shift_id = body["gin_shift_id"]
    buyer = body["buyer_name"]
    price = body["price_cents_per_lb"]
    shift = db.gin_shifts.get(shift_id) if isinstance(shift_id, str) else None
    if shift is None:
        err_id, status = ERR_GIN_SHIFT_NOT_FOUND
        raise ApiError(err_id, "Gin shift not found", status)
    if not isinstance(buyer, str) or not buyer:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "buyer_name must be a non-empty string", status)
    if isinstance(price, bool) or not isinstance(price, int) or price < 1:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "price_cents_per_lb must be an integer >= 1", status)
    if shift["status"] != "RECONCILED":
        err_id, status = ERR_SHIFT_NOT_RECONCILED
        raise ApiError(err_id, "Shift is not RECONCILED", status)
    for s in db.seed_sales.values():
        if s["gin_shift_id"] == shift_id:
            err_id, status = ERR_SHIFT_ALREADY_SOLD
            raise ApiError(err_id, "Shift already has a seed sale", status)
    sold_lbs, net_pool, credits = allocate_seed_pool(shift, price)
    sale = stamp_new({
        "gin_shift_id": shift_id,
        "buyer_name": buyer,
        "price_cents_per_lb": price,
        "sold_lbs": sold_lbs,
        "net_pool_cents": net_pool,
    })
    db.seed_sales[sale["id"]] = sale
    for gid, credit in credits.items():
        post_ledger(gid, shift["season"], "SEED_CREDIT", credit, buyer)
        recompute_draft_settlements(gid, shift["season"])
    return success_object(seed_sale_out(sale), 201)
