"""Order endpoints (PRD §3.4–§3.12)."""
from flask import Blueprint, request

import common
import errors
import lookups
from db import store
from middleware import get_user_context, require_roles
from response import success, list_success
from serializers import (
    serialize_order,
    serialize_line_item,
    serialize_delivery,
    serialize_tip_adjustment,
    serialize_order_issue,
)
from services import order_service, calculations as calc

bp = Blueprint("orders", __name__)


def _customer_owns(user_id, role, order):
    if role == "Customer" and order["customer_id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER)


def _restaurant_owns(user_id, role, order):
    if role == "Restaurant" and order["restaurant_id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER)


# ---------------------------------------------------------------------------
# Place an order (PRD §3.4)
# ---------------------------------------------------------------------------
@bp.route("/orders", methods=["POST"])
def place_order():
    user_id, role = get_user_context()
    require_roles(role, ["Customer"])
    body = common.get_json_body()

    customer_id = common.require_str(body, "customer_id")
    restaurant_id = common.require_str(body, "restaurant_id")
    if "line_items" not in body or body["line_items"] is None:
        raise errors.err(errors.ERR_INVALID_PAYLOAD, "Missing required field: line_items")
    line_items = body["line_items"]
    if not isinstance(line_items, list):
        raise errors.err(errors.ERR_INVALID_PAYLOAD, "line_items must be a list")
    tip_cents = common.optional_int(body, "tip_cents", default=0, minimum=0)
    scheduled_for_raw = body.get("scheduled_for")

    # Existence: FK body fields after path (no path ids here), in order of appearance.
    customer = lookups.get_customer(customer_id)
    restaurant = lookups.get_restaurant(restaurant_id)

    # Ownership: customer places against their own account.
    if role == "Customer" and customer_id != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER)

    # Empty order check.
    if len(line_items) == 0:
        raise errors.err(errors.ERR_EMPTY_ORDER)

    # Parse and validate scheduled_for; decide initial fulfillment_status.
    scheduled_for_dt = None
    scheduled_for_str = None
    if scheduled_for_raw is not None:
        if not isinstance(scheduled_for_raw, str):
            raise errors.err(errors.ERR_INVALID_PAYLOAD, "scheduled_for must be a string")
        scheduled_for_dt = common.parse_iso8601(scheduled_for_raw)
        if scheduled_for_dt is None:
            raise errors.err(errors.ERR_INVALID_PAYLOAD, "scheduled_for must be ISO 8601")
        scheduled_for_str = scheduled_for_raw

    # Validate each line: menu item exists, available, LISTED, belongs to restaurant.
    parsed_lines = []
    for entry in line_items:
        if not isinstance(entry, dict):
            raise errors.err(errors.ERR_INVALID_PAYLOAD, "line item must be an object")
        menu_item_id = common.require_str(entry, "menu_item_id")
        quantity = common.require_int(entry, "quantity", minimum=1)
        menu_item = lookups.get_menu_item(menu_item_id)
        if (
            menu_item["restaurant_id"] != restaurant_id
            or not menu_item["available"]
            or menu_item["status"] != "LISTED"
        ):
            raise errors.err(errors.ERR_ITEM_UNAVAILABLE)
        parsed_lines.append((menu_item, quantity))

    # Restaurant must be open at placement.
    if not restaurant["is_open"]:
        raise errors.err(errors.ERR_ITEM_UNAVAILABLE)

    is_future = scheduled_for_dt is not None and scheduled_for_dt > store.now()

    # prep-slot overlap check for scheduled (future) orders.
    if is_future:
        import datetime
        new_start = scheduled_for_dt
        new_end = scheduled_for_dt + datetime.timedelta(minutes=restaurant["prep_minutes"])
        overlap = calc.prep_overlap_count(restaurant, new_start, new_end)
        if overlap + 1 > restaurant["max_concurrent_prep"]:
            raise errors.err(errors.ERR_PREP_SLOT_CONFLICT)

    # Build the order.
    order = common.init_common(versioned=True)
    order.update({
        "customer_id": customer_id,
        "restaurant_id": restaurant_id,
        "zone_id": restaurant["zone_id"],
        "scheduled_for": scheduled_for_str,
        "_scheduled_for_dt": scheduled_for_dt,
        "order_subtotal_cents": 0,
        "service_fee_cents": 0,
        "delivery_fee_quote_cents": 0,
        "delivery_fee_final_cents": None,
        "tip_cents": tip_cents,
        "surge_multiplier_applied": None,
        "eta_minutes": None,
        "refunded_cents": 0,
        "fulfillment_status": "SCHEDULED" if is_future else "PLACED",
        "billing_status": "UNSETTLED",
    })
    store.orders[order["id"]] = order

    # Create line items.
    for menu_item, quantity in parsed_lines:
        li = common.init_common(versioned=True)
        li.update({
            "order_id": order["id"],
            "menu_item_id": menu_item["id"],
            "quantity": quantity,
            "unit_price_cents": menu_item["price_cents"],
            "extended_price_cents": 0,
            "service_fee_cents": 0,
            "fulfilled_quantity": quantity,
            "status": "ORDERED",
        })
        store.line_items[li["id"]] = li

    zone = store.zones[order["zone_id"]]
    order_service.recompute_order_pricing(order, zone, restaurant)

    return success(serialize_order(order), status=201)


@bp.route("/orders", methods=["GET"])
def list_orders():
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Customer", "Restaurant", "Dasher"])
    limit, offset = common.parse_pagination()
    items = list(store.orders.values())
    for key in ("customer_id", "restaurant_id", "zone_id"):
        val = request.args.get(key)
        if val is not None:
            items = [o for o in items if o[key] == val]
    items = common.sorted_by_creation(items)
    page, total = common.paginate(items, limit, offset)
    return list_success([serialize_order(o) for o in page], limit, offset, total)


@bp.route("/orders/<oid>", methods=["GET"])
def get_order(oid):
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Customer", "Restaurant", "Dasher"])
    o = lookups.get_order(oid)
    return success(serialize_order(o))


# ---------------------------------------------------------------------------
# Add a line item to a SCHEDULED or PLACED order (PRD §3.4)
# ---------------------------------------------------------------------------
@bp.route("/orders/<oid>/line-items", methods=["POST"])
def add_line_item(oid):
    user_id, role = get_user_context()
    require_roles(role, ["Customer"])
    order = lookups.get_order(oid)
    _customer_owns(user_id, role, order)

    body = common.get_json_body()
    menu_item_id = common.require_str(body, "menu_item_id")
    quantity = common.require_int(body, "quantity", minimum=1)

    if order["fulfillment_status"] not in ("SCHEDULED", "PLACED"):
        raise errors.err(errors.ERR_INVALID_ORDER_STATE)

    menu_item = lookups.get_menu_item(menu_item_id)
    restaurant = store.restaurants[order["restaurant_id"]]
    if (
        menu_item["restaurant_id"] != order["restaurant_id"]
        or not menu_item["available"]
        or menu_item["status"] != "LISTED"
    ):
        raise errors.err(errors.ERR_ITEM_UNAVAILABLE)

    li = common.init_common(versioned=True)
    li.update({
        "order_id": order["id"],
        "menu_item_id": menu_item["id"],
        "quantity": quantity,
        "unit_price_cents": menu_item["price_cents"],
        "extended_price_cents": 0,
        "service_fee_cents": 0,
        "fulfilled_quantity": quantity,
        "status": "ORDERED",
    })
    store.line_items[li["id"]] = li

    zone = store.zones[order["zone_id"]]
    order_service.recompute_order_pricing(order, zone, restaurant)
    common.touch(order)
    return success(serialize_line_item(li), status=201)


@bp.route("/orders/<oid>/line-items", methods=["GET"])
def list_order_line_items(oid):
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Customer", "Restaurant", "Dasher"])
    lookups.get_order(oid)
    limit, offset = common.parse_pagination()
    items = [li for li in store.line_items.values() if li["order_id"] == oid]
    items = common.sorted_by_creation(items)
    page, total = common.paginate(items, limit, offset)
    return list_success([serialize_line_item(li) for li in page], limit, offset, total)


@bp.route("/orders/<oid>/deliveries", methods=["GET"])
def list_order_deliveries(oid):
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Customer", "Restaurant", "Dasher"])
    lookups.get_order(oid)
    limit, offset = common.parse_pagination()
    items = [d for d in store.deliveries.values() if d["order_id"] == oid]
    items = common.sorted_by_creation(items)
    page, total = common.paginate(items, limit, offset)
    return list_success([serialize_delivery(d) for d in page], limit, offset, total)


@bp.route("/orders/<oid>/tip-adjustments", methods=["GET"])
def list_order_tip_adjustments(oid):
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Customer", "Restaurant"])
    lookups.get_order(oid)
    limit, offset = common.parse_pagination()
    items = [t for t in store.tip_adjustments.values() if t["order_id"] == oid]
    items = common.sorted_by_creation(items)
    page, total = common.paginate(items, limit, offset)
    return list_success([serialize_tip_adjustment(t) for t in page], limit, offset, total)


@bp.route("/orders/<oid>/issues", methods=["GET"])
def list_order_issues(oid):
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Customer", "Restaurant", "Support"])
    lookups.get_order(oid)
    limit, offset = common.parse_pagination()
    items = [i for i in store.order_issues.values() if i["order_id"] == oid]
    items = common.sorted_by_creation(items)
    page, total = common.paginate(items, limit, offset)
    return list_success([serialize_order_issue(i) for i in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Release (PRD §3.6)
# ---------------------------------------------------------------------------
@bp.route("/orders/<oid>/release", methods=["POST"])
def release_order(oid):
    user_id, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Customer"])
    order = lookups.get_order(oid)
    # Owning customer (or PlatformAdmin) may release.
    _customer_owns(user_id, role, order)
    order_service.release_order(order)
    return success(serialize_order(order))


# ---------------------------------------------------------------------------
# Dispatch (PRD §3.7) — OCC on Order.version
# ---------------------------------------------------------------------------
@bp.route("/orders/<oid>/dispatch", methods=["POST"])
def dispatch_order(oid):
    user_id, role = get_user_context()
    require_roles(role, ["Restaurant"])
    order = lookups.get_order(oid)
    _restaurant_owns(user_id, role, order)

    body = common.get_json_body()
    expected_version = common.require_int(body, "expected_order_version")

    # State: must be PLACED.
    if order["fulfillment_status"] != "PLACED":
        raise errors.err(errors.ERR_INVALID_ORDER_STATE)
    # Restaurant must be open at dispatch.
    restaurant = store.restaurants[order["restaurant_id"]]
    if not restaurant["is_open"]:
        raise errors.err(errors.ERR_RESTAURANT_CLOSED)
    # OCC: expected_order_version must equal current version.
    if expected_version != order["version"]:
        raise errors.err(errors.ERR_STALE_ORDER_VERSION)

    delivery = order_service.dispatch_order(order)
    return success(serialize_delivery(delivery), status=201)


# ---------------------------------------------------------------------------
# Cancel (PRD §3.11)
# ---------------------------------------------------------------------------
@bp.route("/orders/<oid>/cancel", methods=["POST"])
def cancel_order(oid):
    user_id, role = get_user_context()
    require_roles(role, ["Customer"])
    order = lookups.get_order(oid)
    _customer_owns(user_id, role, order)
    order_service.cancel_order(order)
    return success(serialize_order(order))


# ---------------------------------------------------------------------------
# Tip adjustment (PRD §3.10)
# ---------------------------------------------------------------------------
@bp.route("/orders/<oid>/tip-adjustments", methods=["POST"])
def add_tip_adjustment(oid):
    user_id, role = get_user_context()
    require_roles(role, ["Customer"])
    order = lookups.get_order(oid)
    _customer_owns(user_id, role, order)

    body = common.get_json_body()
    delta_cents = common.require_int(body, "delta_cents")
    reason = common.optional_str(body, "reason", default=None)

    # Tip window: only while billing_status == UNSETTLED.
    if order["billing_status"] != "UNSETTLED":
        raise errors.err(errors.ERR_TIP_WINDOW_CLOSED)

    new_tip = order["tip_cents"] + delta_cents
    if new_tip < 0:
        raise errors.err(errors.ERR_TIP_NEGATIVE)

    order["tip_cents"] = new_tip
    common.touch(order)

    adj = common.init_common(versioned=False)
    adj.update({
        "order_id": order["id"],
        "delta_cents": delta_cents,
        "reason": reason,
        "resulting_tip_cents": new_tip,
    })
    store.tip_adjustments[adj["id"]] = adj
    return success(serialize_tip_adjustment(adj), status=201)


# ---------------------------------------------------------------------------
# File a missing-item issue (PRD §3.12)
# ---------------------------------------------------------------------------
@bp.route("/orders/<oid>/issues", methods=["POST"])
def file_issue(oid):
    user_id, role = get_user_context()
    require_roles(role, ["Customer"])
    order = lookups.get_order(oid)
    _customer_owns(user_id, role, order)

    body = common.get_json_body()
    line_item_id = common.require_str(body, "line_item_id")
    missing_quantity = common.require_int(body, "missing_quantity", minimum=1)
    refund_destination = common.optional_enum(
        body, "refund_destination", ["ORIGINAL", "WALLET"], default="ORIGINAL"
    )

    # Order must be DELIVERED to file a missing-item issue.
    if order["fulfillment_status"] != "DELIVERED":
        raise errors.err(errors.ERR_ORDER_NOT_DELIVERED)

    line = lookups.get_line_item(line_item_id)
    if line["order_id"] != order["id"]:
        raise errors.err(errors.ERR_LINE_ITEM_NOT_FOUND)

    issue = common.init_common(versioned=True)
    issue.update({
        "order_id": order["id"],
        "line_item_id": line_item_id,
        "missing_quantity": missing_quantity,
        "refund_destination": refund_destination,
        "refund_amount_cents": 0,
        "status": "OPEN",
    })
    store.order_issues[issue["id"]] = issue
    return success(serialize_order_issue(issue), status=201)
