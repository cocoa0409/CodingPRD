"""DecorationMethod endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import store, new_common_fields
from middleware import endpoint
from response import success, list_response
from serialize import view, view_list
from validation import get_body, require_str, require_enum, require_int, parse_pagination, paginate
from services.lookups import get_shop, get_decoration_method

bp = Blueprint("decoration_methods", __name__)

_RESOURCE_KIND = {"SCREEN_PRINT": "PRESS", "EMBROIDERY": "EMBROIDERY_STATION"}


@bp.route("/decoration-methods", methods=["POST"])
@endpoint("ShopManager")
def create_method():
    body = get_body()
    shop_id = require_str(body, "shop_id")
    get_shop(shop_id)
    method_type = require_enum(body, "method_type", {"SCREEN_PRINT", "EMBROIDERY"})
    name = require_str(body, "name")
    screen_fee = require_int(body, "screen_fee_cents", default=2500)
    digitizing_fee = require_int(body, "digitizing_fee_cents", default=5000)
    extra_color = require_int(body, "extra_color_run_cents", default=75)
    stitch_run = require_int(body, "stitch_run_per_1k_cents", default=90)

    method = new_common_fields()
    method.update({
        "shop_id": shop_id,
        "method_type": method_type,
        "name": name,
        "screen_fee_cents": screen_fee,
        "digitizing_fee_cents": digitizing_fee,
        "extra_color_run_cents": extra_color,
        "stitch_run_per_1k_cents": stitch_run,
        "resource_kind": _RESOURCE_KIND[method_type],
    })
    store.decoration_methods[method["id"]] = method
    return success(view(method), status=201)


@bp.route("/decoration-methods/<method_id>", methods=["GET"])
@endpoint("ShopManager", "ArtStaff", "Customer")
def get_method(method_id):
    return success(view(get_decoration_method(method_id)), status=200)


@bp.route("/decoration-methods", methods=["GET"])
@endpoint("ShopManager", "ArtStaff")
def list_methods():
    limit, offset = parse_pagination()
    shop_id = request.args.get("shop_id")
    items = list(store.decoration_methods.values())
    if shop_id is not None:
        items = [m for m in items if m["shop_id"] == shop_id]
    page, total = paginate(items, limit, offset)
    return list_response(view_list(page), limit, offset, total)
