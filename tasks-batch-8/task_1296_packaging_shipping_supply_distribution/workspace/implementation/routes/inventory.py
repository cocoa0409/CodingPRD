"""Inventory endpoints (PRD §3.3)."""
from flask import Blueprint, request

import db
from errors import err_invalid_request, err_not_found, err_stale_version
from middleware import require_roles, get_json_body, require_int, optional_bool, optional_int
from response import success_object, success_list, parse_pagination, paginate
from serializers import ser_inventory
from services.sourcing import fire_notifications_for_crossing
from util import is_int

bp = Blueprint("inventory", __name__)
PREFIX = "/packaging-distribution"

READ_ROLES = ("PlatformAdmin", "WarehouseOps", "CustomerService")


def _get_inventory(inv_id):
    inv = db.inventory.get(inv_id)
    if inv is None:
        raise err_not_found("Inventory row not found.")
    return inv


@bp.route(f"{PREFIX}/inventory", methods=["POST"])
@require_roles("WarehouseOps", "PlatformAdmin")
def create_inventory():
    body = get_json_body(required=True)
    product_id = body.get("product_id")
    if not isinstance(product_id, str) or not product_id:
        raise err_invalid_request("Missing required field: product_id.")
    warehouse_id = body.get("warehouse_id")
    if not isinstance(warehouse_id, str) or not warehouse_id:
        raise err_invalid_request("Missing required field: warehouse_id.")
    if product_id not in db.products:
        raise err_not_found("Product not found.")
    if warehouse_id not in db.warehouses:
        raise err_not_found("Warehouse not found.")
    if (product_id, warehouse_id) in db.inventory_by_pair:
        raise err_invalid_request("An inventory row already exists for this (product_id, warehouse_id) pair.")
    on_hand_qty = require_int(body, "on_hand_qty")
    if on_hand_qty < 0:
        raise err_invalid_request("Field 'on_hand_qty' must be >= 0.")
    backorderable = optional_bool(body, "backorderable")
    if backorderable is None:
        backorderable = False
    reorder_point_qty = optional_int(body, "reorder_point_qty")
    if reorder_point_qty is None:
        reorder_point_qty = 0
    if reorder_point_qty < 0:
        raise err_invalid_request("Field 'reorder_point_qty' must be >= 0.")

    now = db.now()
    inv = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "product_id": product_id,
        "warehouse_id": warehouse_id,
        "on_hand_qty": on_hand_qty,
        "reserved_qty": 0,
        "backorderable": backorderable,
        "reorder_point_qty": reorder_point_qty,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.inventory[inv["id"]] = inv
    db.inventory_by_pair[(product_id, warehouse_id)] = inv["id"]
    return success_object(ser_inventory(inv), status=201)


@bp.route(f"{PREFIX}/inventory", methods=["GET"])
@require_roles(*READ_ROLES)
def list_inventory():
    limit, offset = parse_pagination(request.args)
    product_f = request.args.get("product_id")
    warehouse_f = request.args.get("warehouse_id")
    items = sorted(db.inventory.values(), key=lambda i: (i["created_at"], i["_seq"]))
    if product_f is not None:
        items = [i for i in items if i["product_id"] == product_f]
    if warehouse_f is not None:
        items = [i for i in items if i["warehouse_id"] == warehouse_f]
    page, pagination = paginate(items, limit, offset)
    return success_list([ser_inventory(i) for i in page], pagination)


@bp.route(f"{PREFIX}/inventory/<inv_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_inventory(inv_id):
    return success_object(ser_inventory(_get_inventory(inv_id)))


@bp.route(f"{PREFIX}/inventory/<inv_id>/receive", methods=["POST"])
@require_roles("WarehouseOps")
def receive_inventory(inv_id):
    inv = _get_inventory(inv_id)
    body = get_json_body(required=True)
    qty = require_int(body, "qty")
    if qty < 1:
        raise err_invalid_request("Field 'qty' must be >= 1.")
    available_before = inv["on_hand_qty"] - inv["reserved_qty"]
    inv["on_hand_qty"] += qty
    db.touch(inv)
    fire_notifications_for_crossing(inv, available_before)
    return success_object(ser_inventory(inv))


@bp.route(f"{PREFIX}/inventory/<inv_id>/adjust", methods=["POST"])
@require_roles("WarehouseOps")
def adjust_inventory(inv_id):
    inv = _get_inventory(inv_id)
    body = get_json_body(required=True)
    expected = body.get("expected_inventory_version")
    if expected is None:
        raise err_invalid_request("Missing required field: expected_inventory_version.")
    if not is_int(expected):
        raise err_invalid_request("Field 'expected_inventory_version' must be an integer.")
    delta_qty = body.get("delta_qty")
    if delta_qty is None:
        raise err_invalid_request("Missing required field: delta_qty.")
    if not is_int(delta_qty):
        raise err_invalid_request("Field 'delta_qty' must be an integer.")
    if expected != inv["version"]:
        raise err_stale_version()
    new_on_hand = inv["on_hand_qty"] + delta_qty
    if new_on_hand < inv["reserved_qty"]:
        raise err_invalid_request("Resulting on_hand_qty must stay >= reserved_qty.")
    available_before = inv["on_hand_qty"] - inv["reserved_qty"]
    inv["on_hand_qty"] = new_on_hand
    db.touch(inv)
    fire_notifications_for_crossing(inv, available_before)
    return success_object(ser_inventory(inv))
