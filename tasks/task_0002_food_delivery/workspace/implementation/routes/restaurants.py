"""Restaurant + Menu Item routes."""

from flask import Blueprint, request as req
import db
from errors import raise_error, ERR_RESTAURANT_NOT_FOUND, ERR_MENU_ITEM_NOT_FOUND, \
    ERR_INVALID_STATE, ERR_ACTIVE_ORDERS_EXIST, ERR_VERSION_CONFLICT, ERR_BAD_REQUEST
from middleware import require_roles
from response import success_response, list_response

bp = Blueprint("restaurants", __name__)


def _get_restaurant_or_404(rid):
    r = db.restaurants.get(rid)
    if not r:
        raise_error(ERR_RESTAURANT_NOT_FOUND, "The referenced restaurant does not exist.")
    return r


def _paginate(request):
    limit = request.args.get("limit", 20, type=int)
    offset = request.args.get("offset", 0, type=int)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    return limit, offset


# ---- CRUD ----

@bp.route("/platform/restaurants", methods=["POST"])
def create_restaurant():
    require_roles("platform_admin")
    body = req.get_json(force=True, silent=True) or {}
    now = db.now_iso()
    r = {
        "id": db.new_id(),
        "name": body.get("name"),
        "cuisine_type": body.get("cuisine_type"),
        "address": body.get("address"),
        "latitude": body.get("latitude"),
        "longitude": body.get("longitude"),
        "commission_rate": body.get("commission_rate"),
        "average_prep_time_minutes": body.get("average_prep_time_minutes"),
        "status": "PENDING_APPROVAL",
        "rating_average": 0.0,
        "rating_count": 0,
        "total_orders_completed": 0,
        "balance_pending_cents": 0,
        "balance_settled_cents": 0,
        "is_accepting_orders": body.get("is_accepting_orders", False),
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.restaurants[r["id"]] = r
    return success_response(r, 201)


@bp.route("/platform/restaurants", methods=["GET"])
def list_restaurants():
    require_roles("platform_admin", "customer")
    limit, offset = _paginate(req)
    items = sorted(db.restaurants.values(), key=lambda x: x["created_at"])
    # filters
    status_f = req.args.get("status")
    cuisine_f = req.args.get("cuisine_type")
    if status_f:
        items = [i for i in items if i["status"] == status_f]
    if cuisine_f:
        items = [i for i in items if i["cuisine_type"] == cuisine_f]
    total = len(items)
    page = items[offset:offset + limit]
    return list_response(page, total, limit, offset)


@bp.route("/platform/restaurants/<restaurant_id>", methods=["GET"])
def get_restaurant(restaurant_id):
    require_roles("platform_admin", "restaurant", "customer")
    r = _get_restaurant_or_404(restaurant_id)
    return success_response(r)


@bp.route("/platform/restaurants/<restaurant_id>", methods=["PATCH"])
def update_restaurant(restaurant_id):
    require_roles("restaurant", "platform_admin")
    r = _get_restaurant_or_404(restaurant_id)
    body = req.get_json(force=True, silent=True) or {}
    # version check
    if "version" in body and body["version"] is not None:
        if body["version"] != r["version"]:
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch.")
    for key in ("name", "address", "is_accepting_orders", "average_prep_time_minutes",
                "cuisine_type", "latitude", "longitude", "commission_rate"):
        if key in body:
            r[key] = body[key]
    r["updated_at"] = db.now_iso()
    r["version"] += 1
    return success_response(r)


# ---- State transitions ----

@bp.route("/platform/restaurants/<restaurant_id>/approve", methods=["POST"])
def approve_restaurant(restaurant_id):
    require_roles("platform_admin")
    r = _get_restaurant_or_404(restaurant_id)
    if r["status"] != "PENDING_APPROVAL":
        raise_error(ERR_INVALID_STATE, "Restaurant must be in PENDING_APPROVAL status.")
    r["status"] = "ACTIVE"
    r["updated_at"] = db.now_iso()
    r["version"] += 1
    return success_response(r)


@bp.route("/platform/restaurants/<restaurant_id>/suspend", methods=["POST"])
def suspend_restaurant(restaurant_id):
    require_roles("platform_admin")
    r = _get_restaurant_or_404(restaurant_id)
    if r["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Restaurant must be ACTIVE to suspend.")
    r["status"] = "SUSPENDED"
    r["is_accepting_orders"] = False
    r["updated_at"] = db.now_iso()
    r["version"] += 1
    # cascade: cancel all PLACED orders for this restaurant
    for o in db.orders.values():
        if o["restaurant_id"] == restaurant_id and o["status"] == "PLACED":
            o["status"] = "CANCELLED_BY_PLATFORM"
            o["cancelled_at"] = db.now_iso()
            o["updated_at"] = db.now_iso()
            o["version"] += 1
    return success_response(r)


@bp.route("/platform/restaurants/<restaurant_id>/reinstate", methods=["POST"])
def reinstate_restaurant(restaurant_id):
    require_roles("platform_admin")
    r = _get_restaurant_or_404(restaurant_id)
    if r["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_STATE, "Restaurant must be SUSPENDED to reinstate.")
    r["status"] = "ACTIVE"
    r["updated_at"] = db.now_iso()
    r["version"] += 1
    return success_response(r)


@bp.route("/platform/restaurants/<restaurant_id>/close", methods=["POST"])
def close_restaurant(restaurant_id):
    require_roles("platform_admin")
    r = _get_restaurant_or_404(restaurant_id)
    if r["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_error(ERR_INVALID_STATE, "Restaurant must be ACTIVE or SUSPENDED to close.")
    if r["status"] == "ACTIVE":
        # precondition: no orders in CONFIRMED or PREPARING
        for o in db.orders.values():
            if o["restaurant_id"] == restaurant_id and o["status"] in ("CONFIRMED", "PREPARING"):
                raise_error(ERR_ACTIVE_ORDERS_EXIST, "Cannot close restaurant while CONFIRMED/PREPARING orders exist.")
        # cancel PLACED orders
        for o in db.orders.values():
            if o["restaurant_id"] == restaurant_id and o["status"] == "PLACED":
                o["status"] = "CANCELLED_BY_PLATFORM"
                o["cancelled_at"] = db.now_iso()
                o["updated_at"] = db.now_iso()
                o["version"] += 1
    # set all menu items unavailable
    for mi in db.menu_items.values():
        if mi["restaurant_id"] == restaurant_id:
            mi["is_available"] = False
            mi["updated_at"] = db.now_iso()
            mi["version"] += 1
    r["status"] = "CLOSED"
    r["is_accepting_orders"] = False
    r["updated_at"] = db.now_iso()
    r["version"] += 1
    return success_response(r)


# ---- Menu Items ----

@bp.route("/platform/restaurants/<restaurant_id>/menu-items", methods=["POST"])
def create_menu_item(restaurant_id):
    require_roles("restaurant")
    _get_restaurant_or_404(restaurant_id)
    body = req.get_json(force=True, silent=True) or {}
    # Validate minimum price
    base_price = body.get("base_price_cents")
    if base_price is not None and base_price < 100:
        raise_error(ERR_BAD_REQUEST, "base_price_cents must be >= 100.")
    now = db.now_iso()
    mi = {
        "id": db.new_id(),
        "restaurant_id": restaurant_id,
        "name": body.get("name"),
        "description": body.get("description"),
        "base_price_cents": body.get("base_price_cents"),
        "category": body.get("category"),
        "is_available": body.get("is_available", True),
        "prep_time_minutes": body.get("prep_time_minutes"),
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.menu_items[mi["id"]] = mi
    return success_response(mi, 201)


@bp.route("/platform/restaurants/<restaurant_id>/menu-items", methods=["GET"])
def list_menu_items(restaurant_id):
    require_roles("restaurant", "customer", "platform_admin")
    _get_restaurant_or_404(restaurant_id)
    limit, offset = _paginate(req)
    items = sorted(
        [mi for mi in db.menu_items.values() if mi["restaurant_id"] == restaurant_id],
        key=lambda x: x["created_at"],
    )
    cat_f = req.args.get("category")
    avail_f = req.args.get("is_available")
    if cat_f:
        items = [i for i in items if i["category"] == cat_f]
    if avail_f is not None:
        avail_bool = avail_f.lower() == "true"
        items = [i for i in items if i["is_available"] == avail_bool]
    total = len(items)
    page = items[offset:offset + limit]
    return list_response(page, total, limit, offset)


@bp.route("/platform/restaurants/<restaurant_id>/menu-items/<menu_item_id>", methods=["PATCH"])
def update_menu_item(restaurant_id, menu_item_id):
    require_roles("restaurant")
    _get_restaurant_or_404(restaurant_id)
    mi = db.menu_items.get(menu_item_id)
    if not mi or mi["restaurant_id"] != restaurant_id:
        raise_error(ERR_MENU_ITEM_NOT_FOUND, "Menu item not found or does not belong to this restaurant.")
    body = req.get_json(force=True, silent=True) or {}
    if "version" in body and body["version"] is not None:
        if body["version"] != mi["version"]:
            raise_error(ERR_VERSION_CONFLICT, "Version mismatch.")
    for key in ("name", "base_price_cents", "is_available", "prep_time_minutes", "description"):
        if key in body:
            mi[key] = body[key]
    mi["updated_at"] = db.now_iso()
    mi["version"] += 1
    return success_response(mi)
