"""Restaurant and MenuItem endpoints (PRD §3.2)."""
from flask import Blueprint, request

import common
import errors
import lookups
from db import store
from middleware import get_user_context, require_roles
from response import success, list_success
from serializers import serialize_restaurant, serialize_menu_item, serialize_line_item

bp = Blueprint("restaurants", __name__)

ALL_ROLES = ["PlatformAdmin", "Restaurant", "Dasher", "Customer"]


def _owns_restaurant(user_id, role, restaurant):
    """Entity-backed Restaurant must own the restaurant it mutates."""
    if role == "Restaurant" and restaurant["id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER)


# ---------------------------------------------------------------------------
# Restaurant
# ---------------------------------------------------------------------------
@bp.route("/restaurants", methods=["POST"])
def create_restaurant():
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Restaurant"])
    body = common.get_json_body()

    zone_id = common.require_str(body, "zone_id")
    name = common.require_str(body, "name")
    route_distance_km = common.require_int(body, "route_distance_km", minimum=1)
    is_open = common.optional_bool(body, "is_open", default=True)
    prep_minutes = common.optional_int(body, "prep_minutes", default=15, minimum=1)
    max_concurrent_prep = common.optional_int(body, "max_concurrent_prep", default=1, minimum=1)

    lookups.get_zone(zone_id)  # FK existence

    r = common.init_common(versioned=True)
    r.update({
        "zone_id": zone_id,
        "name": name,
        "route_distance_km": route_distance_km,
        "is_open": is_open,
        "prep_minutes": prep_minutes,
        "max_concurrent_prep": max_concurrent_prep,
        "status": "ACTIVE",
    })
    store.restaurants[r["id"]] = r
    return success(serialize_restaurant(r), status=201)


@bp.route("/restaurants", methods=["GET"])
def list_restaurants():
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    limit, offset = common.parse_pagination()
    zone_filter = request.args.get("zone_id")
    items = list(store.restaurants.values())
    if zone_filter is not None:
        items = [r for r in items if r["zone_id"] == zone_filter]
    items = common.sorted_by_creation(items)
    page, total = common.paginate(items, limit, offset)
    return list_success([serialize_restaurant(r) for r in page], limit, offset, total)


@bp.route("/restaurants/<rid>", methods=["GET"])
def get_restaurant(rid):
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    r = lookups.get_restaurant(rid)
    return success(serialize_restaurant(r))


@bp.route("/restaurants/<rid>", methods=["PATCH"])
def update_restaurant(rid):
    user_id, role = get_user_context()
    require_roles(role, ["Restaurant"])
    r = lookups.get_restaurant(rid)
    _owns_restaurant(user_id, role, r)
    body = common.get_json_body()

    changed = False
    if "is_open" in body and body["is_open"] is not None:
        r["is_open"] = common.optional_bool(body, "is_open")
        changed = True
    if "prep_minutes" in body and body["prep_minutes"] is not None:
        r["prep_minutes"] = common.optional_int(body, "prep_minutes", minimum=1)
        changed = True
    if changed:
        common.touch(r)
    return success(serialize_restaurant(r))


@bp.route("/restaurants/<rid>/deactivate", methods=["POST"])
def deactivate_restaurant(rid):
    user_id, role = get_user_context()
    require_roles(role, ["Restaurant"])
    r = lookups.get_restaurant(rid)
    _owns_restaurant(user_id, role, r)

    if r["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_RESTAURANT_STATE)
    active = {"PLACED", "ROUTED", "PICKED_UP"}
    for o in store.orders.values():
        if o["restaurant_id"] == r["id"] and o["fulfillment_status"] in active:
            raise errors.err(errors.ERR_RESTAURANT_HAS_ACTIVE_ORDERS)

    r["status"] = "DEACTIVATED"
    common.touch(r)
    for m in store.menu_items.values():
        if m["restaurant_id"] == r["id"] and m["status"] == "LISTED":
            m["status"] = "DELISTED"
            common.touch(m)
    return success(serialize_restaurant(r))


# ---------------------------------------------------------------------------
# MenuItem
# ---------------------------------------------------------------------------
@bp.route("/restaurants/<rid>/menu-items", methods=["POST"])
def add_menu_item(rid):
    user_id, role = get_user_context()
    require_roles(role, ["Restaurant"])
    r = lookups.get_restaurant(rid)
    _owns_restaurant(user_id, role, r)
    body = common.get_json_body()

    name = common.require_str(body, "name")
    price_cents = common.require_int(body, "price_cents", minimum=1)
    available = common.optional_bool(body, "available", default=True)

    m = common.init_common(versioned=True)
    m.update({
        "restaurant_id": r["id"],
        "name": name,
        "price_cents": price_cents,
        "available": available,
        "status": "LISTED",
    })
    store.menu_items[m["id"]] = m
    return success(serialize_menu_item(m), status=201)


@bp.route("/restaurants/<rid>/menu-items", methods=["GET"])
def list_menu_items(rid):
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    lookups.get_restaurant(rid)
    limit, offset = common.parse_pagination()
    items = [m for m in store.menu_items.values() if m["restaurant_id"] == rid]
    items = common.sorted_by_creation(items)
    page, total = common.paginate(items, limit, offset)
    return list_success([serialize_menu_item(m) for m in page], limit, offset, total)


@bp.route("/menu-items/<mid>", methods=["GET"])
def get_menu_item(mid):
    _, role = get_user_context()
    require_roles(role, ALL_ROLES)
    m = lookups.get_menu_item(mid)
    return success(serialize_menu_item(m))


@bp.route("/menu-items/<mid>/line-items", methods=["GET"])
def list_menu_item_line_items(mid):
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Restaurant"])
    lookups.get_menu_item(mid)
    limit, offset = common.parse_pagination()
    items = [li for li in store.line_items.values() if li["menu_item_id"] == mid]
    items = common.sorted_by_creation(items)
    page, total = common.paginate(items, limit, offset)
    return list_success([serialize_line_item(li) for li in page], limit, offset, total)


@bp.route("/menu-items/<mid>", methods=["PATCH"])
def update_menu_item(mid):
    user_id, role = get_user_context()
    require_roles(role, ["Restaurant"])
    m = lookups.get_menu_item(mid)
    if role == "Restaurant" and m["restaurant_id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER)
    body = common.get_json_body()

    changed = False
    if "available" in body and body["available"] is not None:
        m["available"] = common.optional_bool(body, "available")
        changed = True
    if "price_cents" in body and body["price_cents"] is not None:
        m["price_cents"] = common.optional_int(body, "price_cents", minimum=1)
        changed = True
    if changed:
        common.touch(m)
    return success(serialize_menu_item(m))


@bp.route("/menu-items/<mid>/delist", methods=["POST"])
def delist_menu_item(mid):
    user_id, role = get_user_context()
    require_roles(role, ["Restaurant"])
    m = lookups.get_menu_item(mid)
    if role == "Restaurant" and m["restaurant_id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER)
    if m["status"] != "LISTED":
        raise errors.err(errors.ERR_INVALID_MENU_ITEM_STATE)
    m["status"] = "DELISTED"
    common.touch(m)
    return success(serialize_menu_item(m))
