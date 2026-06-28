"""PaintBarItem routes (PRD §3.7; SCAFFOLD §1.5).

RBAC:
  POST /paint-bar-items                 StudioManager
  GET  /paint-bar-items/{id}            StudioStaff, StudioManager
  GET  /paint-bar-items                 StudioStaff, StudioManager
  POST /paint-bar-items/{id}/restock    StudioManager
  POST /paint-bar-items/{id}/discontinue StudioManager
"""

from flask import Blueprint, request

from db import db, new_id, stamp_common, touch
from middleware import get_caller, require_roles
from response import success, list_success, parse_pagination, paginate
from services import serializers
from services.lookup import get_item
from services.validation import (require_body, require_str, require_int,
                                 require_enum, optional_int)

bp = Blueprint("paint_bar_items", __name__)

STAFF_MANAGER = {"StudioStaff", "StudioManager"}
CATEGORIES = {"GLAZE", "UNDERGLAZE", "TOOL", "TOGO_KIT"}


def _recompute_low_stock(item):
    item["low_stock"] = item["on_hand_qty"] <= item["reorder_threshold"]


@bp.route("/paint-bar-items", methods=["POST"])
def create_item():
    caller = get_caller()
    require_roles(caller, {"StudioManager"})
    payload = require_body(request.get_json(silent=True))
    sku = require_str(payload, "sku")
    name = require_str(payload, "name")
    category = require_enum(payload, "category", CATEGORIES)
    unit_price_cents = require_int(payload, "unit_price_cents", minimum=0)
    reorder_threshold = optional_int(payload, "reorder_threshold", default=0, minimum=0)

    record = {
        "id": new_id(),
        "sku": sku,
        "name": name,
        "category": category,
        "unit_price_cents": unit_price_cents,
        "on_hand_qty": 0,
        "reorder_threshold": reorder_threshold,
        "low_stock": False,
        "status": "ACTIVE",
    }
    _recompute_low_stock(record)
    stamp_common(record)
    db.paint_bar_items[record["id"]] = record
    return success(serializers.paint_bar_item(record), status=201)


@bp.route("/paint-bar-items/<item_id>", methods=["GET"])
def fetch_item(item_id):
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    item = get_item(item_id)
    return success(serializers.paint_bar_item(item))


@bp.route("/paint-bar-items", methods=["GET"])
def list_items():
    caller = get_caller()
    require_roles(caller, STAFF_MANAGER)
    limit, offset = parse_pagination(request.args)
    records = list(db.paint_bar_items.values())
    category = request.args.get("category")
    if category is not None:
        records = [r for r in records if r["category"] == category]
    low_stock = request.args.get("low_stock")
    if low_stock is not None:
        want = low_stock.lower() in ("true", "1", "yes")
        records = [r for r in records if r["low_stock"] == want]
    window, total = paginate(records, limit, offset)
    return list_success([serializers.paint_bar_item(r) for r in window], limit, offset, total)


@bp.route("/paint-bar-items/<item_id>/restock", methods=["POST"])
def restock_item(item_id):
    caller = get_caller()
    require_roles(caller, {"StudioManager"})
    item = get_item(item_id)
    payload = require_body(request.get_json(silent=True))
    qty = require_int(payload, "qty", minimum=0)
    item["on_hand_qty"] += qty
    _recompute_low_stock(item)
    touch(item)
    return success(serializers.paint_bar_item(item))


@bp.route("/paint-bar-items/<item_id>/discontinue", methods=["POST"])
def discontinue_item(item_id):
    caller = get_caller()
    require_roles(caller, {"StudioManager"})
    item = get_item(item_id)
    item["status"] = "DISCONTINUED"
    touch(item)
    return success(serializers.paint_bar_item(item))
