"""VanStockItem read/adjust endpoints (creation lives on technicians routes)."""
from flask import Blueprint, request

from db import store, touch
from errors import err_not_found, err_validation
from middleware import auth, require_technician_self
from response import success
from serializers import serialize
from services.cascades import reorder_trigger, wall_now
from util import Field, validate_body, parse_pagination, paginate

bp = Blueprint("van_stock", __name__)

ROLES = ["OpsAdmin", "Dispatcher", "Technician"]


def _get_item(item_id):
    item = store.van_stock.get(item_id)
    if item is None:
        raise err_not_found("VanStockItem not found")
    return item


@bp.route("/roadside/van-stock/<vanStockItemId>", methods=["GET"])
def get_item(vanStockItemId):
    auth(ROLES)
    return success(serialize("van_item", _get_item(vanStockItemId)))


@bp.route("/roadside/van-stock", methods=["GET"])
def list_items():
    auth(ROLES)
    limit, offset = parse_pagination(request.args)
    tech_f = request.args.get("technician_id")
    class_f = request.args.get("part_class")
    items = sorted(store.van_stock.values(), key=lambda r: r["_seq"])
    if tech_f is not None:
        items = [i for i in items if i["technician_id"] == tech_f]
    if class_f is not None:
        items = [i for i in items if i["part_class"] == class_f]
    page, total, has_more = paginate(items, limit, offset)
    return success([serialize("van_item", i) for i in page],
                   response_type="array",
                   pagination={"limit": limit, "offset": offset,
                               "total_count": total, "has_more": has_more})


@bp.route("/roadside/van-stock/<vanStockItemId>/adjust", methods=["POST"])
def adjust_item(vanStockItemId):
    uid, role = auth(["OpsAdmin", "Technician"])
    item = _get_item(vanStockItemId)
    if role == "Technician":
        require_technician_self(uid, item["technician_id"])
    vals = validate_body(request.get_json(silent=True), [
        Field("qty_delta", "int", required=True),
        Field("reason", "string", required=True),
    ])
    new_qty = item["qty_on_hand"] + vals["qty_delta"]
    if new_qty < 0:
        raise err_validation("qty_delta would drive qty_on_hand negative")
    item["qty_on_hand"] = new_qty
    touch(item, wall_now())
    reorder_trigger(item)
    return success(serialize("van_item", item))
