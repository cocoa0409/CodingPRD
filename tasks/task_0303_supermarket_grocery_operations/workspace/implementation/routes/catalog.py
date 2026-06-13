"""Departments and Products."""
import re

from flask import Blueprint, request, g

from auth import require_role
from common import (
    stamp_new, touch, require_dict, get_str, get_int, get_bool,
    pagination_params, paginate,
)
from db import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_DUPLICATE_RESOURCE, ERR_PRODUCT_DISCONTINUED,
)
from lookup import get_department, get_product
from inventory import reorder_flag
from response import success, list_response
from serializers import ser_department, ser_product, ser_price_plan, ser_promotion

bp = Blueprint("catalog", __name__)

DEPT_CODE_RE = re.compile(r"^[A-Z_]+$")


# ---------------- Departments ----------------

@bp.route("/departments", methods=["POST"])
def create_department():
    require_role("StoreManager")
    body = require_dict(request.get_json(silent=True))
    code = get_str(body, "code")
    name = get_str(body, "name")
    shrink = get_int(body, "shrink_alert_bps", required=False, default=200, min_value=0, max_value=10000)
    if not DEPT_CODE_RE.match(code):
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "code must be uppercase A-Z and underscore")
    # uniqueness
    for d in db.departments.values():
        if d["code"] == code:
            raise ApiError(ERR_DUPLICATE_RESOURCE[0], ERR_DUPLICATE_RESOURCE[1], "department code already exists")
    rec = stamp_new({
        "code": code,
        "name": name,
        "shrink_alert_bps": shrink,
    })
    db.departments[rec["id"]] = rec
    return success(ser_department(rec), status=201)


@bp.route("/departments", methods=["GET"])
def list_departments():
    require_role("StoreManager", "PriceManager", "ReceivingClerk", "InventoryAuditor", "Cashier")
    limit, offset = pagination_params(request.args)
    page, total = paginate(list(db.departments.values()), limit, offset)
    return list_response([ser_department(d) for d in page], limit, offset, total)


@bp.route("/departments/<did>", methods=["GET"])
def get_department_route(did):
    require_role("StoreManager", "PriceManager", "ReceivingClerk", "InventoryAuditor", "Cashier")
    d = get_department(did)
    return success(ser_department(d))


# ---------------- Products ----------------

@bp.route("/products", methods=["POST"])
def create_product():
    require_role("StoreManager", "PriceManager")
    body = require_dict(request.get_json(silent=True))
    # FK existence first (priority 3): resolve department_id leniently
    dept_id = body.get("department_id")
    if not isinstance(dept_id, str) or not dept_id:
        raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "department_id is required")
    get_department(dept_id)

    name = get_str(body, "name")
    sell_by_weight = get_bool(body, "sell_by_weight", required=False, default=False)
    unit_price = get_int(body, "unit_price_cents", min_value=0)
    is_perishable = get_bool(body, "is_perishable", required=False, default=False)
    reorder_point = get_int(body, "reorder_point_qty", required=False, default=0, min_value=0)

    sku = get_str(body, "sku", required=False, default=None)
    plu = get_str(body, "plu", required=False, default=None)
    # conditional-required + mutual exclusion
    if sell_by_weight:
        if not plu:
            raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "plu required when sell_by_weight=true")
        sku = None
    else:
        if not sku:
            raise ApiError(ERR_INVALID_REQUEST[0], ERR_INVALID_REQUEST[1], "sku required when sell_by_weight=false")
        plu = None

    # uniqueness (priority 5): sku/plu unique where present
    if sku is not None:
        for p in db.products.values():
            if p.get("sku") == sku:
                raise ApiError(ERR_DUPLICATE_RESOURCE[0], ERR_DUPLICATE_RESOURCE[1], "sku already exists")
    if plu is not None:
        for p in db.products.values():
            if p.get("plu") == plu:
                raise ApiError(ERR_DUPLICATE_RESOURCE[0], ERR_DUPLICATE_RESOURCE[1], "plu already exists")

    rec = stamp_new({
        "department_id": dept_id,
        "sku": sku,
        "plu": plu,
        "name": name,
        "sell_by_weight": sell_by_weight,
        "unit_price_cents": unit_price,
        "is_perishable": is_perishable,
        "reorder_point_qty": reorder_point,
        "on_hand_qty": 0,
        "on_hand_value_cents": 0,
        "reorder_flagged": False,
        "status": "ACTIVE",
    })
    reorder_flag(rec)  # on_hand 0 <= reorder_point => flagged
    db.products[rec["id"]] = rec
    return success(ser_product(rec), status=201)


@bp.route("/products", methods=["GET"])
def list_products():
    require_role("StoreManager", "PriceManager", "ReceivingClerk", "InventoryAuditor", "Cashier")
    limit, offset = pagination_params(request.args)
    items = list(db.products.values())
    dept = request.args.get("department_id")
    if dept is not None:
        items = [p for p in items if p["department_id"] == dept]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    rf = request.args.get("reorder_flagged")
    if rf is not None:
        want = rf.lower() in ("true", "1")
        items = [p for p in items if p["reorder_flagged"] == want]
    page, total = paginate(items, limit, offset)
    return list_response([ser_product(p) for p in page], limit, offset, total)


@bp.route("/products/<pid>", methods=["GET"])
def get_product_route(pid):
    require_role("StoreManager", "PriceManager", "ReceivingClerk", "InventoryAuditor", "Cashier")
    p = get_product(pid)
    return success(ser_product(p))


@bp.route("/products/<pid>/discontinue", methods=["POST"])
def discontinue_product(pid):
    require_role("StoreManager")
    p = get_product(pid)
    if p["status"] != "ACTIVE":
        raise ApiError(ERR_PRODUCT_DISCONTINUED[0], ERR_PRODUCT_DISCONTINUED[1], "product already discontinued")
    p["status"] = "DISCONTINUED"
    touch(p)
    return success(ser_product(p))


@bp.route("/products/<pid>/price-plans", methods=["GET"])
def list_product_price_plans(pid):
    from routes.pricing import derive_window_status, project_status
    require_role("StoreManager", "PriceManager", "Cashier")
    get_product(pid)
    limit, offset = pagination_params(request.args)
    items = [pp for pp in db.price_plans.values() if pp["product_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [pp for pp in items if derive_window_status(pp) == status]
    page, total = paginate(items, limit, offset)
    return list_response([project_status(pp, ser_price_plan) for pp in page], limit, offset, total)


@bp.route("/products/<pid>/promotions", methods=["GET"])
def list_product_promotions(pid):
    from routes.pricing import derive_window_status, project_status
    require_role("StoreManager", "PriceManager", "Cashier")
    get_product(pid)
    limit, offset = pagination_params(request.args)
    items = [pr for pr in db.promotions.values() if pr["product_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [pr for pr in items if derive_window_status(pr) == status]
    page, total = paginate(items, limit, offset)
    return list_response([project_status(pr, ser_promotion) for pr in page], limit, offset, total)
