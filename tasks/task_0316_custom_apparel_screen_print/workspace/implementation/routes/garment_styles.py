"""GarmentStyle and BlankSku endpoints (PRD §3.1, §2.8)."""
from flask import Blueprint, request

from db import store, new_common_fields
from errors import err
from middleware import endpoint
from response import success, list_response
from serialize import view, view_list
from validation import (
    get_body, require_str, require_int, require_positive_int,
    require_str_array, parse_pagination, paginate,
)
from services import inventory
from services.lookups import (
    get_shop, get_garment_style, get_blank_sku_under_style, blank_skus_of_style,
)

bp = Blueprint("garment_styles", __name__)


@bp.route("/garment-styles", methods=["POST"])
@endpoint("ShopManager")
def create_style():
    body = get_body()
    shop_id = require_str(body, "shop_id")
    get_shop(shop_id)
    sku_code = require_str(body, "sku_code")
    name = require_str(body, "name")
    blank_cost = require_int(body, "blank_cost_cents")
    if blank_cost < 0:
        raise err("ERR_INVALID_REQUEST", "blank_cost_cents must be non-negative")
    available_colors = require_str_array(body, "available_colors")
    available_sizes = require_str_array(body, "available_sizes")

    # sku_code unique per shop (PRD §3.1).
    for s in store.garment_styles.values():
        if s["shop_id"] == shop_id and s["sku_code"] == sku_code:
            raise err("ERR_INVALID_REQUEST", "sku_code already in use for this shop")

    style = new_common_fields()
    style.update({
        "shop_id": shop_id,
        "sku_code": sku_code,
        "name": name,
        "blank_cost_cents": blank_cost,
        "available_colors": list(available_colors),
        "available_sizes": list(available_sizes),
    })
    store.garment_styles[style["id"]] = style
    return success(view(style), status=201)


@bp.route("/garment-styles/<style_id>", methods=["GET"])
@endpoint("ShopManager", "ArtStaff", "Customer")
def get_style(style_id):
    return success(view(get_garment_style(style_id)), status=200)


@bp.route("/garment-styles", methods=["GET"])
@endpoint("ShopManager", "ArtStaff", "Customer")
def list_styles():
    limit, offset = parse_pagination()
    shop_id = request.args.get("shop_id")
    items = list(store.garment_styles.values())
    if shop_id is not None:
        items = [s for s in items if s["shop_id"] == shop_id]
    page, total = paginate(items, limit, offset)
    return list_response(view_list(page), limit, offset, total)


# ---- BlankSku (sub-resource of GarmentStyle) ----

@bp.route("/garment-styles/<style_id>/blank-skus", methods=["POST"])
@endpoint("ShopManager")
def create_blank_sku(style_id):
    style = get_garment_style(style_id)
    body = get_body()
    color = require_str(body, "color")
    size = require_str(body, "size")
    total_stock = require_positive_int(body, "total_stock_qty")
    if color not in style["available_colors"]:
        raise err("ERR_INVALID_REQUEST", "color not in style's available_colors")
    if size not in style["available_sizes"]:
        raise err("ERR_INVALID_REQUEST", "size not in style's available_sizes")

    sku = new_common_fields()
    sku.update({
        "garment_style_id": style_id,
        "color": color,
        "size": size,
        "total_stock_qty": total_stock,
        "on_hand_qty": total_stock,
        "reserved_qty": 0,
    })
    store.blank_skus[sku["id"]] = sku
    return success(view(sku), status=201)


@bp.route("/garment-styles/<style_id>/blank-skus/<sku_id>/restock", methods=["POST"])
@endpoint("ShopManager")
def restock_blank_sku(style_id, sku_id):
    sku = get_blank_sku_under_style(style_id, sku_id)
    body = get_body()
    add_qty = require_positive_int(body, "add_qty")
    inventory.restock(sku, add_qty)
    return success(view(sku), status=200)


@bp.route("/garment-styles/<style_id>/blank-skus", methods=["GET"])
@endpoint("ShopManager", "ArtStaff", "Customer")
def list_blank_skus(style_id):
    get_garment_style(style_id)
    limit, offset = parse_pagination()
    color = request.args.get("color")
    size = request.args.get("size")
    items = blank_skus_of_style(style_id)
    if color is not None:
        items = [s for s in items if s["color"] == color]
    if size is not None:
        items = [s for s in items if s["size"] == size]
    page, total = paginate(items, limit, offset)
    return list_response(view_list(page), limit, offset, total)


@bp.route("/garment-styles/<style_id>/blank-skus/<sku_id>", methods=["GET"])
@endpoint("ShopManager", "ArtStaff", "Customer")
def get_blank_sku(style_id, sku_id):
    return success(view(get_blank_sku_under_style(style_id, sku_id)), status=200)
