"""Product endpoints."""
from flask import Blueprint, request
from db import db
from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION
from middleware import require_roles
from response import success
from services.helpers import (
    parse_pagination, paginate, body, require_fields, require_int, require_str,
    require_enum, new_common_fields, touch,
)

bp = Blueprint("products", __name__)

BOARD_KINDS = {"REGULAR", "FIRE_RATED", "MOISTURE_RATED"}
LENGTHS = {8, 10, 12, 14, 16}
THICKNESSES = {"1/2", "5/8", "3/4"}
RATED = {"FIRE_RATED", "MOISTURE_RATED"}


def _get_product_or_404(pid):
    p = db.products.get(pid)
    if p is None:
        raise ApiError(ERR_NOT_FOUND, "Product not found", 404)
    return p


@bp.route("/supply/products", methods=["POST"])
def create_product():
    require_roles("WarehouseManager")
    b = body()
    require_fields(
        b, "sku", "board_kind", "length_ft", "width_ft", "thickness_in",
        "sheets_per_bundle", "unit_price_cents_per_sheet", "lead_time_days",
    )
    sku = require_str(b, "sku")
    board_kind = require_enum(b, "board_kind", BOARD_KINDS)
    length_ft = require_int(b, "length_ft")
    if length_ft not in LENGTHS:
        raise ApiError(ERR_VALIDATION, "length_ft must be one of 8, 10, 12, 14, 16", 400)
    width_ft = require_int(b, "width_ft")
    if width_ft != 4:
        raise ApiError(ERR_VALIDATION, "width_ft must be 4", 400)
    thickness_in = require_enum(b, "thickness_in", THICKNESSES)
    sheets_per_bundle = require_int(b, "sheets_per_bundle", min_val=1)
    unit_price = require_int(b, "unit_price_cents_per_sheet", min_val=1)
    lead_time_days = require_int(b, "lead_time_days", min_val=0)
    if board_kind in RATED and lead_time_days < 1:
        raise ApiError(ERR_VALIDATION, "lead_time_days must be >= 1 for rated kinds", 400)
    if board_kind == "REGULAR" and lead_time_days != 0:
        # PRD: lead time is zero for REGULAR board
        raise ApiError(ERR_VALIDATION, "lead_time_days must be 0 for REGULAR board", 400)
    # Uniqueness on sku
    for p in db.products.values():
        if p["sku"] == sku:
            raise ApiError(ERR_VALIDATION, f"sku {sku} already exists", 400)
    prod = new_common_fields()
    prod.update({
        "sku": sku,
        "board_kind": board_kind,
        "length_ft": length_ft,
        "width_ft": width_ft,
        "thickness_in": thickness_in,
        "sheets_per_bundle": sheets_per_bundle,
        "unit_price_cents_per_sheet": unit_price,
        "lead_time_days": lead_time_days,
        "active": True,
    })
    db.products[prod["id"]] = prod
    return success(prod, status=201)


@bp.route("/supply/products/<pid>", methods=["GET"])
def get_product(pid):
    require_roles(
        "CreditManager", "EstimatorUser", "DispatcherUser", "Foreman",
        "AccountsReceivableUser", "WarehouseManager",
    )
    return success(_get_product_or_404(pid))


@bp.route("/supply/products", methods=["GET"])
def list_products():
    require_roles(
        "CreditManager", "EstimatorUser", "DispatcherUser", "Foreman",
        "AccountsReceivableUser", "WarehouseManager",
    )
    limit, offset = parse_pagination()
    board_kind = request.args.get("board_kind")
    active_arg = request.args.get("active")
    items = list(db.products.values())
    if board_kind is not None:
        items = [p for p in items if p["board_kind"] == board_kind]
    if active_arg is not None:
        want = active_arg.lower() in ("true", "1", "yes")
        items = [p for p in items if p["active"] == want]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    page, pg = paginate(items, limit, offset)
    return success(page, is_list=True, pagination=pg)


@bp.route("/supply/products/<pid>", methods=["PATCH"])
def update_product(pid):
    require_roles("WarehouseManager")
    p = _get_product_or_404(pid)
    b = body()
    if "unit_price_cents_per_sheet" in b:
        p["unit_price_cents_per_sheet"] = require_int(b, "unit_price_cents_per_sheet", min_val=1)
    if "lead_time_days" in b:
        new_lt = require_int(b, "lead_time_days", min_val=0)
        if p["board_kind"] in RATED and new_lt < 1:
            raise ApiError(ERR_VALIDATION, "lead_time_days must be >= 1 for rated kinds", 400)
        if p["board_kind"] == "REGULAR" and new_lt != 0:
            raise ApiError(ERR_VALIDATION, "lead_time_days must be 0 for REGULAR board", 400)
        p["lead_time_days"] = new_lt
    if "active" in b:
        v = b["active"]
        if not isinstance(v, bool):
            raise ApiError(ERR_VALIDATION, "active must be a boolean", 400)
        p["active"] = v
    touch(p)
    return success(p)
