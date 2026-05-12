"""Store orders + order lines."""

from flask import Blueprint, g, request

import clock
import db
import errors
import helpers
import response
import serializers
from middleware import auth_required
from services import audit


bp = Blueprint("store_orders", __name__, url_prefix="/supply-chain/store-orders")


MIN_ORDER_UNITS = 1
MAX_ORDER_UNITS = 10000


def _ensure_owner(store_order):
    if g.user_role == "StoreManager" and store_order["store_id"] != g.user_id:
        errors.raise_error(errors.ERR_FORBIDDEN, "StoreManager may only act on their own store's orders.")


def _now_minute_of_day():
    n = clock.now()
    return n.hour * 60 + n.minute


def _seconds_until_close(store):
    """Return number of seconds from now until the day's order_window_close_minute (UTC)."""
    n = clock.now()
    today_close = n.replace(hour=store["order_window_close_minute"] // 60,
                            minute=store["order_window_close_minute"] % 60,
                            second=0, microsecond=0)
    return (today_close - n).total_seconds()


def _within_cutoff(store):
    """True if we're already within `cutoff_minutes_before_close` of close."""
    secs = _seconds_until_close(store)
    return secs < store["cutoff_minutes_before_close"] * 60


@bp.route("", methods=["POST"])
@auth_required("StoreManager")
def create_order():
    body = helpers.get_json_body()
    if "target_delivery_date" not in body:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "Missing target_delivery_date.")

    store = db.stores.get(g.user_id)
    if store is None:
        errors.raise_error(errors.ERR_FORBIDDEN, "Acting StoreManager has no associated store.")

    oid = db.new_id()
    common = helpers.common_create()
    order = {
        "id": oid,
        "store_id": g.user_id,
        "target_delivery_date": body["target_delivery_date"],
        "submitted_at": None,
        "cancelled_at": None,
        "total_units": 0,
        "total_value_cents": 0,
        "consolidation_batch_id": None,
        "status": "DRAFT",
        **common,
    }
    db.store_orders[oid] = order
    audit.append(target_type="StoreOrder", target_id=oid, action="CREATE_ORDER",
                 payload={"target_delivery_date": order["target_delivery_date"]})
    return response.created(serializers.store_order_dict(order))


def _lines_for(order_id):
    return [l for l in db.order_lines.values() if l["store_order_id"] == order_id]


@bp.route("/<oid>/lines", methods=["POST"])
@auth_required("StoreManager")
def append_line(oid):
    order = db.store_orders.get(oid)
    if order is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"StoreOrder {oid} not found.")
    _ensure_owner(order)
    if order["status"] != "DRAFT":
        errors.raise_error(errors.ERR_INVALID_STATE, "Lines may only be appended on DRAFT orders.")

    body = helpers.get_json_body()
    if "recipe_id" not in body or "quantity" not in body:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "Missing recipe_id or quantity.")
    rid = body["recipe_id"]
    qty = body["quantity"]

    if rid not in db.recipes:
        errors.raise_error(errors.ERR_REFERENCE_NOT_FOUND, f"Recipe {rid} not found.")

    store = db.stores[order["store_id"]]
    if rid not in store["catalog_permission"]:
        errors.raise_error(errors.ERR_CATALOG_PERMISSION_DENIED,
                           "Recipe is not in the store's catalog permission.")
    if not isinstance(qty, int) or qty < MIN_ORDER_UNITS or qty > MAX_ORDER_UNITS:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE,
                           f"quantity must be in [{MIN_ORDER_UNITS}, {MAX_ORDER_UNITS}].")

    lid = db.new_id()
    line = {
        "id": lid,
        "store_order_id": oid,
        "recipe_id": rid,
        "quantity": qty,
        "line_value_cents": 0,
        "created_at": clock.now(),
    }
    db.order_lines[lid] = line
    audit.append(target_type="StoreOrder", target_id=oid, action="APPEND_LINE",
                 payload={"recipe_id": rid, "quantity": qty})
    return response.created(serializers.order_line_dict(line))


@bp.route("/<oid>/submit", methods=["POST"])
@auth_required("StoreManager")
def submit_order(oid):
    order = db.store_orders.get(oid)
    if order is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"StoreOrder {oid} not found.")
    _ensure_owner(order)
    body = helpers.get_json_body()

    if order["status"] != "DRAFT":
        errors.raise_error(errors.ERR_INVALID_STATE, "Only DRAFT orders may be submitted.")
    helpers.check_occ(order, body.get("version"))

    store = db.stores[order["store_id"]]
    if store["status"] != "ACTIVE":
        errors.raise_error(errors.ERR_INVALID_STATE, "Store is not ACTIVE.")

    # Order window check (UTC minute-of-day).
    mod = _now_minute_of_day()
    if not (store["order_window_open_minute"] <= mod < store["order_window_close_minute"]):
        errors.raise_error(errors.ERR_ORDER_WINDOW_CLOSED, "Outside the daily ordering window.")

    lines = _lines_for(oid)
    if not lines:
        errors.raise_error(errors.ERR_INVALID_STATE, "Order must have at least one line.")

    for line in lines:
        if line["recipe_id"] not in store["catalog_permission"]:
            errors.raise_error(errors.ERR_CATALOG_PERMISSION_DENIED,
                               "An order line refers to a recipe not in catalog permission.")
        if not (MIN_ORDER_UNITS <= line["quantity"] <= MAX_ORDER_UNITS):
            errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE,
                               "An order line quantity is out of range.")

    # Lock line values; recompute totals.
    total_units = 0
    total_value_cents = 0
    for line in lines:
        recipe = db.recipes[line["recipe_id"]]
        line["line_value_cents"] = line["quantity"] * recipe["unit_price_cents"]
        total_units += line["quantity"]
        total_value_cents += line["line_value_cents"]

    order["status"] = "SUBMITTED"
    order["submitted_at"] = clock.now()
    order["total_units"] = total_units
    order["total_value_cents"] = total_value_cents
    helpers.bump(order)

    audit.append(target_type="StoreOrder", target_id=oid, action="SUBMIT_ORDER",
                 payload={"total_units": total_units, "total_value_cents": total_value_cents},
                 external_systems=["POS", "ERP"])
    return response.ok(serializers.store_order_dict(order))


@bp.route("/<oid>/cancel", methods=["POST"])
@auth_required("StoreManager")
def cancel_order(oid):
    order = db.store_orders.get(oid)
    if order is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"StoreOrder {oid} not found.")
    _ensure_owner(order)
    body = helpers.get_json_body()

    if order["status"] not in ("DRAFT", "SUBMITTED"):
        errors.raise_error(errors.ERR_INVALID_STATE, "Order is not in a cancellable state.")
    helpers.check_occ(order, body.get("version"))

    store = db.stores[order["store_id"]]
    if _within_cutoff(store):
        errors.raise_error(errors.ERR_ORDER_CUTOFF_PASSED,
                           "Within cutoff window before close — modifications forbidden.")

    if order["status"] == "SUBMITTED" and order["consolidation_batch_id"] is not None:
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "Order has been consolidated; cannot cancel.")

    order["status"] = "CANCELLED"
    order["cancelled_at"] = clock.now()
    helpers.bump(order)
    audit.append(target_type="StoreOrder", target_id=oid, action="CANCEL_ORDER",
                 payload={"prior_status": "SUBMITTED" if order["submitted_at"] else "DRAFT"})
    return response.ok(serializers.store_order_dict(order))


@bp.route("/<oid>", methods=["PATCH"])
@auth_required("StoreManager")
def patch_order(oid):
    order = db.store_orders.get(oid)
    if order is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"StoreOrder {oid} not found.")
    _ensure_owner(order)
    if order["status"] != "DRAFT":
        errors.raise_error(errors.ERR_INVALID_STATE, "Header may only be updated on DRAFT orders.")

    body = helpers.get_json_body()
    helpers.check_occ(order, body.get("version"))

    store = db.stores[order["store_id"]]
    if _within_cutoff(store):
        errors.raise_error(errors.ERR_ORDER_CUTOFF_PASSED,
                           "Within cutoff window before close — modifications forbidden.")

    if "target_delivery_date" in body:
        order["target_delivery_date"] = body["target_delivery_date"]
    helpers.bump(order)
    audit.append(target_type="StoreOrder", target_id=oid, action="UPDATE_ORDER",
                 payload={"target_delivery_date": order["target_delivery_date"]})
    return response.ok(serializers.store_order_dict(order))


@bp.route("", methods=["GET"])
@auth_required("PlatformAdmin", "CentralKitchenPlanner", "StoreManager")
def list_orders():
    limit, offset = helpers.parse_pagination()
    items = list(db.store_orders.values())

    store_id = request.args.get("store_id")
    status_filter = request.args.get("status")
    target_date = request.args.get("target_delivery_date")

    if g.user_role == "StoreManager":
        items = [o for o in items if o["store_id"] == g.user_id]
    if store_id:
        items = [o for o in items if o["store_id"] == store_id]
    if status_filter:
        items = [o for o in items if o["status"] == status_filter]
    if target_date:
        items = [o for o in items if o["target_delivery_date"] == target_date]

    items.sort(key=lambda o: o["created_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok([serializers.store_order_dict(o) for o in page],
                            limit=limit, offset=offset, total_count=total)


@bp.route("/<oid>", methods=["GET"])
@auth_required("PlatformAdmin", "CentralKitchenPlanner", "StoreManager")
def read_order(oid):
    order = db.store_orders.get(oid)
    if order is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"StoreOrder {oid} not found.")
    if g.user_role == "StoreManager":
        _ensure_owner(order)
    return response.ok(serializers.store_order_dict(order))
