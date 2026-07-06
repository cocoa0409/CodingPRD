"""InventoryItem endpoints."""
from flask import Blueprint, request

import db
from models import base_fields
from middleware import authenticate, get_identity_optional
from validators import (
    get_body, require_grade, get_pagination, paginate, sorted_by_created, lookup,
)
from response import success, success_list
from errors import err, ERR_INVALID_REQUEST, ERR_INVALID_GRADE_FOR_NEW
from services import public, public_list, compute_item_price

bp = Blueprint("inventory", __name__)


def make_inventory_item(product_id, is_used, condition_grade, consignment_id=None):
    item = base_fields()
    item.update({
        "product_id": product_id,
        "consignment_id": consignment_id,
        "is_used": is_used,
        "condition_grade": condition_grade,
        "status": "AVAILABLE",
        "hold_start_at": None,
        "hold_end_at": None,
        "list_price_cents": 0,
    })
    # price depends on product + (optional) consignment already stored
    db.db.inventory_items[item["id"]] = item
    item["list_price_cents"] = compute_item_price(item)
    return item


@bp.route("/shop/inventory-items", methods=["POST"])
def create_inventory_item():
    authenticate({"StoreClerk", "Manager"})
    body = get_body()
    product_id = body.get("product_id")
    if not isinstance(product_id, str) or not product_id:
        raise err(ERR_INVALID_REQUEST, "product_id required")
    is_used = body.get("is_used")
    if not isinstance(is_used, bool):
        raise err(ERR_INVALID_REQUEST, "is_used must be boolean")
    grade = require_grade(body, "condition_grade")
    consignment_id = body.get("consignment_id")
    # existence checks
    lookup(db.db.products, product_id)
    if consignment_id is not None:
        lookup(db.db.consignments, consignment_id)
    # business_safety: NEW must be M or NM
    if not is_used and grade not in ("M", "NM"):
        raise err(ERR_INVALID_GRADE_FOR_NEW, "New copy must be graded M or NM")
    item = make_inventory_item(product_id, is_used, grade, consignment_id)
    return success(public(item), 201)


@bp.route("/shop/inventory-items/<iid>", methods=["GET"])
def read_inventory_item(iid):
    get_identity_optional()
    item = lookup(db.db.inventory_items, iid)
    return success(public(item), 200)


@bp.route("/shop/inventory-items", methods=["GET"])
def list_inventory_items():
    get_identity_optional()
    limit, offset = get_pagination()
    product_id = request.args.get("product_id")
    consignment_id = request.args.get("consignment_id")
    status = request.args.get("status")
    is_used = request.args.get("is_used")
    items = list(db.db.inventory_items.values())
    if product_id is not None:
        items = [i for i in items if i["product_id"] == product_id]
    if consignment_id is not None:
        items = [i for i in items if i.get("consignment_id") == consignment_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    if is_used is not None:
        want = is_used.lower() == "true"
        items = [i for i in items if i["is_used"] == want]
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(public_list(page), limit, offset, total)
