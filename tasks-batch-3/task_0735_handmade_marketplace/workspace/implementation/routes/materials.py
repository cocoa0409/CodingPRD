"""Material endpoints."""
from flask import Blueprint, request
from auth import get_auth, require_role, require_shop_owner
from db import store, stamp_common, touch
from envelope import success
from errors import raise_err, ERR_VALIDATION, ERR_MATERIAL_NOT_FOUND, ERR_SHOP_NOT_FOUND, ERR_RESTOCK_INVALID_QTY
from helpers import get_json_body, require_field, opt_field, parse_pagination, paginate, sort_by_created
from serializers import material_view
from services import find_shop, update_material_status, cascade_material_freed

bp = Blueprint("materials", __name__)


@bp.route("/seller/materials", methods=["POST"])
def create():
    user_id, role = get_auth()
    require_role(role, {"Seller"})
    body = get_json_body()
    shop_id = require_field(body, "shop_id", str)
    name = require_field(body, "name", str)
    stock_qty = require_field(body, "stock_qty", int)
    require_shop_owner(user_id, role, shop_id)
    if find_shop(shop_id) is None:
        raise_err(ERR_SHOP_NOT_FOUND, "shop not found")
    unit = opt_field(body, "unit", str, "piece")
    thr = opt_field(body, "reorder_threshold", int, 0)
    if stock_qty < 0 or thr < 0:
        raise_err(ERR_VALIDATION, "stock_qty and reorder_threshold must be >= 0")
    rec = {
        "shop_id": shop_id,
        "name": name,
        "unit": unit,
        "stock_qty": stock_qty,
        "reorder_threshold": thr,
        "status": "IN_STOCK",
    }
    update_material_status(rec)
    stamp_common(rec)
    store.materials[rec["id"]] = rec
    return success(material_view(rec), status=201)


@bp.route("/seller/materials/<mat_id>", methods=["GET"])
def fetch(mat_id):
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin"})
    m = store.materials.get(mat_id)
    if m is None:
        raise_err(ERR_MATERIAL_NOT_FOUND, "not found")
    require_shop_owner(user_id, role, m["shop_id"])
    return success(material_view(m))


@bp.route("/seller/materials", methods=["GET"])
def list_():
    user_id, role = get_auth()
    require_role(role, {"Seller", "PlatformAdmin"})
    limit, offset = parse_pagination()
    shop_id = request.args.get("shop_id")
    status = request.args.get("status")
    items = list(store.materials.values())
    if shop_id is not None:
        items = [x for x in items if x["shop_id"] == shop_id]
    if status is not None:
        items = [x for x in items if x["status"] == status]
    if role == "Seller":
        items = [x for x in items if x["shop_id"] == user_id]
    items = sort_by_created(items)
    page, pmeta = paginate(items, limit, offset)
    return success([material_view(x) for x in page], response_type="array", pagination=pmeta)


@bp.route("/seller/materials/<mat_id>/restock", methods=["POST"])
def restock(mat_id):
    user_id, role = get_auth()
    require_role(role, {"Seller"})
    m = store.materials.get(mat_id)
    if m is None:
        raise_err(ERR_MATERIAL_NOT_FOUND, "not found")
    require_shop_owner(user_id, role, m["shop_id"])
    body = get_json_body()
    # restock_qty must be present and a positive integer
    if "restock_qty" not in body or body["restock_qty"] is None:
        raise_err(ERR_RESTOCK_INVALID_QTY, "missing restock_qty")
    q = body["restock_qty"]
    if not isinstance(q, int) or isinstance(q, bool) or q <= 0:
        raise_err(ERR_RESTOCK_INVALID_QTY, "restock_qty must be positive integer")
    m["stock_qty"] += q
    update_material_status(m)
    touch(m)
    cascade_material_freed(m)
    return success(material_view(m))
