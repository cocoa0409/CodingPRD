"""ShippingOrder routes."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, parse_dt, is_valid_datetime
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_WINDOW,
    ERR_EMPTY_SHIPMENT,
    ERR_FORBIDDEN,
    ERR_GROWER_NOT_FOUND,
    ERR_WAREHOUSE_NOT_FOUND,
    ERR_BALE_NOT_FOUND,
    ERR_SHIPPING_ORDER_NOT_FOUND,
    ERR_MIXED_GROWER_SHIPMENT,
    ERR_BALE_WAREHOUSE_MISMATCH,
    ERR_BALE_NOT_SHIPPABLE,
    ERR_DOCK_WINDOW_CONFLICT,
    ERR_ORDER_NOT_CONFIRMABLE,
    ERR_ORDER_NOT_SHIPPABLE,
    ERR_ORDER_NOT_CANCELLABLE,
)
from middleware import (
    get_context,
    require_role,
    grower_owns,
    parse_pagination,
    get_json_body,
    require_fields,
)
from response import success_object
from services.core import (
    stamp_new,
    touch,
    post_ledger,
    sorted_entities,
    paginate,
    recompute_warehouse_count,
    recompute_grower_balance,
)
from services.calc import compute_storage_charge_cents, recompute_draft_settlements

bp = Blueprint("shipping_orders", __name__)

GAP = timedelta(minutes=30)


def order_out(o):
    return {
        "id": o["id"],
        "warehouse_id": o["warehouse_id"],
        "grower_id": o["grower_id"],
        "bale_ids": list(o["bale_ids"]),
        "dock_number": o["dock_number"],
        "load_start": o["load_start"],
        "load_end": o["load_end"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def _non_terminal_receipt(bale_id):
    for r in db.warehouse_receipts.values():
        if r["bale_id"] == bale_id and r["status"] in ("ACTIVE", "PLEDGED", "RELEASED"):
            return r
    return None


def _shippable(bale):
    if bale["custody_status"] != "WAREHOUSED":
        return False
    r = _non_terminal_receipt(bale["id"])
    if r is None or r["status"] not in ("ACTIVE", "RELEASED"):
        return False
    return True


def _bale_grower(bale):
    m = db.modules.get(bale["module_id"])
    return m["grower_id"] if m else None


@bp.route("/gin-ops/shipping-orders", methods=["POST"])
def create_order():
    user_id, role = get_context()
    require_role(role, {"Grower", "WarehouseManager"})
    body = get_json_body()
    require_fields(body, ["warehouse_id", "grower_id", "bale_ids", "dock_number", "load_start", "load_end"])
    warehouse_id = body["warehouse_id"]
    grower_id = body["grower_id"]
    bale_ids = body["bale_ids"]
    dock_number = body["dock_number"]
    load_start_raw = body["load_start"]
    load_end_raw = body["load_end"]

    # Existence of FK references
    wh = db.warehouses.get(warehouse_id) if isinstance(warehouse_id, str) else None
    if wh is None:
        err_id, status = ERR_WAREHOUSE_NOT_FOUND
        raise ApiError(err_id, "Warehouse not found", status)
    grower = db.growers.get(grower_id) if isinstance(grower_id, str) else None
    if grower is None:
        err_id, status = ERR_GROWER_NOT_FOUND
        raise ApiError(err_id, "Grower not found", status)
    # Grower may only create for own id
    if role == "Grower" and user_id != grower_id:
        err_id, status = ERR_FORBIDDEN
        raise ApiError(err_id, "Grower may only create shipping orders for themselves", status)
    # Body shape
    if not isinstance(bale_ids, list):
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "bale_ids must be a list", status)
    if len(bale_ids) == 0:
        err_id, status = ERR_EMPTY_SHIPMENT
        raise ApiError(err_id, "bale_ids must be non-empty", status)
    if isinstance(dock_number, bool) or not isinstance(dock_number, int):
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "dock_number must be an integer", status)
    if dock_number < 1 or dock_number > wh["dock_count"]:
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "dock_number out of range", status)
    if not is_valid_datetime(load_start_raw) or not is_valid_datetime(load_end_raw):
        err_id, status = ERR_INVALID_REQUEST
        raise ApiError(err_id, "load_start/load_end must be valid datetimes", status)
    load_start = parse_dt(load_start_raw)
    load_end = parse_dt(load_end_raw)
    if load_end <= load_start:
        err_id, status = ERR_INVALID_WINDOW
        raise ApiError(err_id, "load_end must be strictly later than load_start", status)
    # Bale existence
    bales = []
    for bid in bale_ids:
        b = db.bales.get(bid) if isinstance(bid, str) else None
        if b is None:
            err_id, status = ERR_BALE_NOT_FOUND
            raise ApiError(err_id, "Bale not found", status)
        bales.append(b)
    # State gate: shippable predicate on every listed bale
    for b in bales:
        if not _shippable(b):
            err_id, status = ERR_BALE_NOT_SHIPPABLE
            raise ApiError(err_id, "A listed bale is not shippable", status)
    # Dock window conflict
    for o in db.shipping_orders.values():
        if o["warehouse_id"] != warehouse_id or o["dock_number"] != dock_number:
            continue
        if o["status"] == "CANCELLED":
            continue
        o_start = o["_load_start_dt"]
        o_end = o["_load_end_dt"]
        if not (load_end + GAP <= o_start or o_end + GAP <= load_start):
            err_id, status = ERR_DOCK_WINDOW_CONFLICT
            raise ApiError(err_id, "Dock window conflict (30-minute turnaround)", status)
    # Cross-entity coherence
    for b in bales:
        if _bale_grower(b) != grower_id:
            err_id, status = ERR_MIXED_GROWER_SHIPMENT
            raise ApiError(err_id, "A bale belongs to another grower", status)
        r = _non_terminal_receipt(b["id"])
        if r is None or r["warehouse_id"] != warehouse_id:
            err_id, status = ERR_BALE_WAREHOUSE_MISMATCH
            raise ApiError(err_id, "A bale's receipt sits at another warehouse", status)

    order = stamp_new({
        "warehouse_id": warehouse_id,
        "grower_id": grower_id,
        "bale_ids": list(bale_ids),
        "dock_number": dock_number,
        "load_start": load_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "load_end": load_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "_load_start_dt": load_start,
        "_load_end_dt": load_end,
        "status": "DRAFT",
    })
    db.shipping_orders[order["id"]] = order
    return success_object(order_out(order), 201)


@bp.route("/gin-ops/shipping-orders/<oid>", methods=["GET"])
def get_order(oid):
    user_id, role = get_context()
    o = db.shipping_orders.get(oid)
    if o is None:
        err_id, status = ERR_SHIPPING_ORDER_NOT_FOUND
        raise ApiError(err_id, "Shipping order not found", status)
    grower_owns(user_id, role, o["grower_id"])
    return success_object(order_out(o))


@bp.route("/gin-ops/shipping-orders", methods=["GET"])
def list_orders():
    user_id, role = get_context()
    limit, offset = parse_pagination()
    args = request.args
    items = list(db.shipping_orders.values())
    if role == "Grower":
        items = [o for o in items if o["grower_id"] == user_id]
        if args.get("grower_id") and args["grower_id"] != user_id:
            err_id, status = ERR_FORBIDDEN
            raise ApiError(err_id, "Grower may only access own shipping orders", status)
    if args.get("warehouse_id"):
        items = [o for o in items if o["warehouse_id"] == args["warehouse_id"]]
    if args.get("grower_id"):
        items = [o for o in items if o["grower_id"] == args["grower_id"]]
    if args.get("status"):
        items = [o for o in items if o["status"] == args["status"]]
    items = sorted_entities(items)
    return paginate([order_out(o) for o in items], limit, offset)


@bp.route("/gin-ops/shipping-orders/<oid>/confirm", methods=["POST"])
def confirm_order(oid):
    user_id, role = get_context()
    require_role(role, {"Grower", "WarehouseManager"})
    o = db.shipping_orders.get(oid)
    if o is None:
        err_id, status = ERR_SHIPPING_ORDER_NOT_FOUND
        raise ApiError(err_id, "Shipping order not found", status)
    grower_owns(user_id, role, o["grower_id"])
    if o["status"] != "DRAFT":
        err_id, status = ERR_ORDER_NOT_CONFIRMABLE
        raise ApiError(err_id, "Order is not DRAFT", status)
    for bid in o["bale_ids"]:
        b = db.bales.get(bid)
        if b is None or not _shippable(b):
            err_id, status = ERR_BALE_NOT_SHIPPABLE
            raise ApiError(err_id, "A listed bale is not shippable", status)
    o["status"] = "CONFIRMED"
    touch(o)
    return success_object(order_out(o))


@bp.route("/gin-ops/shipping-orders/<oid>/ship", methods=["POST"])
def ship_order(oid):
    user_id, role = get_context()
    require_role(role, {"WarehouseManager"})
    o = db.shipping_orders.get(oid)
    if o is None:
        err_id, status = ERR_SHIPPING_ORDER_NOT_FOUND
        raise ApiError(err_id, "Shipping order not found", status)
    if o["status"] != "CONFIRMED":
        err_id, status = ERR_ORDER_NOT_SHIPPABLE
        raise ApiError(err_id, "Order is not CONFIRMED", status)
    # Check ALL bales shippable before mutating any
    bales = []
    receipts = []
    for bid in o["bale_ids"]:
        b = db.bales.get(bid)
        if b is None or not _shippable(b):
            err_id, status = ERR_BALE_NOT_SHIPPABLE
            raise ApiError(err_id, "A listed bale is not shippable", status)
        bales.append(b)
        receipts.append(_non_terminal_receipt(bid))
    # Commit cascade
    o["status"] = "SHIPPED"
    touch(o)
    end_dt = db.clock_datetime()
    affected_growers = set()
    for b, r in zip(bales, receipts):
        r["status"] = "SHIPPED"
        touch(r)
        b["custody_status"] = "SHIPPED"
        touch(b)
        gid = _bale_grower(b)
        m = db.modules.get(b["module_id"])
        season = m["season"] if m else None
        charge = compute_storage_charge_cents(r, end_dt)
        if charge > 0:
            post_ledger(gid, season, "STORAGE_CHARGE", -charge, r["receipt_number"])
        else:
            recompute_grower_balance(gid)
        affected_growers.add((gid, season))
    wh = db.warehouses.get(o["warehouse_id"])
    if wh is not None:
        recompute_warehouse_count(wh["id"])
        touch(wh)
    for gid, season in affected_growers:
        if gid and season:
            recompute_draft_settlements(gid, season)
    return success_object(order_out(o))


@bp.route("/gin-ops/shipping-orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    user_id, role = get_context()
    require_role(role, {"Grower", "WarehouseManager"})
    o = db.shipping_orders.get(oid)
    if o is None:
        err_id, status = ERR_SHIPPING_ORDER_NOT_FOUND
        raise ApiError(err_id, "Shipping order not found", status)
    grower_owns(user_id, role, o["grower_id"])
    if o["status"] not in ("DRAFT", "CONFIRMED"):
        err_id, status = ERR_ORDER_NOT_CANCELLABLE
        raise ApiError(err_id, "Order cannot be cancelled from its current state", status)
    o["status"] = "CANCELLED"
    touch(o)
    return success_object(order_out(o))


@bp.route("/gin-ops/shipping-orders/<oid>/bales", methods=["GET"])
def list_order_bales(oid):
    user_id, role = get_context()
    o = db.shipping_orders.get(oid)
    if o is None:
        err_id, status = ERR_SHIPPING_ORDER_NOT_FOUND
        raise ApiError(err_id, "Shipping order not found", status)
    grower_owns(user_id, role, o["grower_id"])
    limit, offset = parse_pagination()
    from routes.bales import bale_out
    # In bale_ids order
    items = [db.bales[bid] for bid in o["bale_ids"] if bid in db.bales]
    total = len(items)
    page = items[offset:offset + limit]
    from response import success_list
    return success_list([bale_out(b) for b in page], limit, offset, total)
