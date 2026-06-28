"""RestockOrder endpoints: fetch, list, fulfill."""
from flask import Blueprint, request

import errors
from db import db, public, touch
from middleware import get_identity, require_role
from response import success, list_success
from validation import parse_pagination, paginate

bp = Blueprint("restock", __name__)


def _get_order_or_404(order_id):
    rec = db.restock_orders.get(order_id)
    if rec is None:
        raise errors.not_found("Restock order not found")
    return rec


@bp.get("/restock-orders/<id>")
def get_order(id):
    _, role = get_identity()
    require_role(role, ["FieldSupervisor", "PlatformAdmin"])
    rec = _get_order_or_404(id)
    return success(public(rec))


@bp.get("/restock-orders")
def list_orders():
    _, role = get_identity()
    require_role(role, ["FieldSupervisor", "PlatformAdmin"])
    limit, offset = parse_pagination()
    damage_report_id = request.args.get("damage_report_id")
    inventory_item_id = request.args.get("inventory_item_id")
    status = request.args.get("status")
    records = list(db.restock_orders.values())
    if damage_report_id is not None:
        records = [r for r in records if r.get("damage_report_id") == damage_report_id]
    if inventory_item_id is not None:
        records = [r for r in records if r["inventory_item_id"] == inventory_item_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return list_success([public(r) for r in page], limit, offset, total)


@bp.post("/restock-orders/<id>/fulfill")
def fulfill_order(id):
    _, role = get_identity()
    require_role(role, ["PlatformAdmin"])
    order = _get_order_or_404(id)
    if order["status"] != "REQUESTED":
        raise errors.invalid_state()
    item = db.inventory_items.get(order["inventory_item_id"])
    if item is not None:
        item["on_hand_qty"] = item["on_hand_qty"] + order["quantity"]
        touch(item)
    order["status"] = "FULFILLED"
    touch(order)
    return success(public(order))
