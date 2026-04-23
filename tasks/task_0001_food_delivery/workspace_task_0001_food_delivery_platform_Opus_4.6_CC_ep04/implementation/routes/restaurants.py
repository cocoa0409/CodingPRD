from flask import Blueprint, request
from middleware.auth import require_roles
from storage import db
from models.restaurant import Restaurant
from models.menu_item import MenuItem
from response import success_response
from errors import raise_error, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_INVALID_STATE, ERR_VALIDATION

bp = Blueprint("restaurants", __name__)


def get_restaurant_or_404(restaurant_id):
    r = db.restaurants.get(restaurant_id)
    if not r:
        raise_error(ERR_NOT_FOUND, "Restaurant not found.")
    return r


@bp.route("/api/restaurants", methods=["POST"])
@require_roles("PlatformAdmin")
def create_restaurant():
    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name")
    address = data.get("address")
    lat = data.get("lat")
    lng = data.get("lng")
    commission_rate_override = data.get("commission_rate_override")

    if not name or not isinstance(name, str) or len(name.strip()) == 0:
        raise_error(ERR_VALIDATION, "Name is required and must be non-empty.")
    if len(name) > 120:
        raise_error(ERR_VALIDATION, "Name must be at most 120 characters.")
    if address is None:
        raise_error(ERR_VALIDATION, "Address is required.")
    if lat is None or lng is None:
        raise_error(ERR_VALIDATION, "lat and lng are required.")
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        raise_error(ERR_VALIDATION, "lat and lng must be numbers.")

    for r in db.restaurants.values():
        if r.name == name and r.status != "CLOSED":
            raise_error(ERR_VALIDATION, "Restaurant name must be unique among active restaurants.")

    if commission_rate_override is not None:
        if not isinstance(commission_rate_override, (int, float)):
            raise_error(ERR_VALIDATION, "commission_rate_override must be a number.")
        if commission_rate_override < 0.05 or commission_rate_override > 0.35:
            raise_error(ERR_VALIDATION, "commission_rate_override must be in [0.05, 0.35].")

    restaurant = Restaurant(name, address, float(lat), float(lng), commission_rate_override)
    db.restaurants[restaurant.id] = restaurant
    return success_response(restaurant.to_dict(), 201)


@bp.route("/api/restaurants", methods=["GET"])
@require_roles("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
def list_restaurants():
    status_filter = request.args.get("status")
    limit = request.args.get("limit", 10, type=int)
    offset = request.args.get("offset", 0, type=int)

    if limit < 1 or limit > 100:
        raise_error(ERR_VALIDATION, "limit must be between 1 and 100.")
    if offset < 0:
        raise_error(ERR_VALIDATION, "offset must be >= 0.")

    items = sorted(db.restaurants.values(), key=lambda r: r.created_at)
    if status_filter:
        items = [r for r in items if r.status == status_filter]

    total_count = len(items)
    page = items[offset:offset + limit]
    return success_response(
        [r.to_dict() for r in page],
        pagination={
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + limit < total_count,
        },
    )


@bp.route("/api/restaurants/<restaurant_id>", methods=["GET"])
@require_roles("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
def get_restaurant(restaurant_id):
    r = get_restaurant_or_404(restaurant_id)
    return success_response(r.to_dict())


@bp.route("/api/restaurants/<restaurant_id>", methods=["PATCH"])
@require_roles("PlatformAdmin", "Restaurant")
def update_restaurant(restaurant_id):
    r = get_restaurant_or_404(restaurant_id)
    if request.user_role == "Restaurant" and request.user_id != r.id:
        raise_error(ERR_FORBIDDEN, "Cannot update another restaurant's profile.")

    data = request.get_json(force=True, silent=True) or {}
    version = data.get("version")
    r.check_version(version)

    if "address" in data:
        r.address = data["address"]
    if "lat" in data:
        if not isinstance(data["lat"], (int, float)):
            raise_error(ERR_VALIDATION, "lat must be a number.")
        r.lat = float(data["lat"])
    if "lng" in data:
        if not isinstance(data["lng"], (int, float)):
            raise_error(ERR_VALIDATION, "lng must be a number.")
        r.lng = float(data["lng"])
    if "commission_rate_override" in data:
        val = data["commission_rate_override"]
        if val is not None:
            if not isinstance(val, (int, float)):
                raise_error(ERR_VALIDATION, "commission_rate_override must be a number.")
            if val < 0.05 or val > 0.35:
                raise_error(ERR_VALIDATION, "commission_rate_override must be in [0.05, 0.35].")
        r.commission_rate_override = val

    r.touch()
    return success_response(r.to_dict())


@bp.route("/api/restaurants/<restaurant_id>/approve", methods=["POST"])
@require_roles("PlatformAdmin")
def approve_restaurant(restaurant_id):
    r = get_restaurant_or_404(restaurant_id)
    if r.status != "PENDING_APPROVAL":
        raise_error(ERR_INVALID_STATE, "Restaurant is not in PENDING_APPROVAL state.")
    r.status = "ACTIVE"
    r.touch()
    return success_response(r.to_dict())


@bp.route("/api/restaurants/<restaurant_id>/suspend", methods=["POST"])
@require_roles("PlatformAdmin")
def suspend_restaurant(restaurant_id):
    r = get_restaurant_or_404(restaurant_id)
    if r.status != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Restaurant is not in ACTIVE state.")
    r.status = "SUSPENDED"
    for order in db.orders.values():
        if order.restaurant_id == r.id and order.status == "PLACED":
            order.status = "CANCELLED"
            if order.payment_status in ("UNPAID", "AUTHORIZED"):
                order.payment_status = "VOIDED"
            order.touch()
    r.touch()
    return success_response(r.to_dict())


@bp.route("/api/restaurants/<restaurant_id>/reinstate", methods=["POST"])
@require_roles("PlatformAdmin")
def reinstate_restaurant(restaurant_id):
    r = get_restaurant_or_404(restaurant_id)
    if r.status != "SUSPENDED":
        raise_error(ERR_INVALID_STATE, "Restaurant is not in SUSPENDED state.")
    r.status = "ACTIVE"
    r.touch()
    return success_response(r.to_dict())


@bp.route("/api/restaurants/<restaurant_id>/settle", methods=["POST"])
@require_roles("PlatformAdmin")
def settle_restaurant(restaurant_id):
    r = get_restaurant_or_404(restaurant_id)
    r.pending_settlement_cents = 0
    r.touch()
    return success_response(r.to_dict())


@bp.route("/api/restaurants/<restaurant_id>/menu-items", methods=["POST"])
@require_roles("Restaurant", "PlatformAdmin")
def create_menu_item(restaurant_id):
    r = get_restaurant_or_404(restaurant_id)
    if request.user_role == "Restaurant" and request.user_id != r.id:
        raise_error(ERR_FORBIDDEN, "Cannot create menu items for another restaurant.")

    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name")
    price_cents = data.get("price_cents")
    is_listed = data.get("is_listed", True)

    if not name or not isinstance(name, str) or len(name.strip()) == 0:
        raise_error(ERR_VALIDATION, "Name is required.")
    if price_cents is None or not isinstance(price_cents, int):
        raise_error(ERR_VALIDATION, "price_cents is required and must be an integer.")
    if price_cents < 1 or price_cents > 1000000:
        raise_error(ERR_VALIDATION, "price_cents must be between 1 and 1000000.")

    item = MenuItem(r.id, name, price_cents, is_listed)
    db.menu_items[item.id] = item
    return success_response(item.to_dict(), 201)


@bp.route("/api/menu-items/<item_id>", methods=["PATCH"])
@require_roles("Restaurant", "PlatformAdmin")
def update_menu_item(item_id):
    item = db.menu_items.get(item_id)
    if not item:
        raise_error(ERR_NOT_FOUND, "Menu item not found.")

    if request.user_role == "Restaurant" and request.user_id != item.restaurant_id:
        raise_error(ERR_FORBIDDEN, "Cannot update another restaurant's menu item.")

    data = request.get_json(force=True, silent=True) or {}
    version = data.get("version")
    item.check_version(version)

    if "price_cents" in data:
        pc = data["price_cents"]
        if not isinstance(pc, int):
            raise_error(ERR_VALIDATION, "price_cents must be an integer.")
        if pc < 1 or pc > 1000000:
            raise_error(ERR_VALIDATION, "price_cents must be between 1 and 1000000.")
        item.price_cents = pc
    if "is_listed" in data:
        item.is_listed = bool(data["is_listed"])

    item.touch()
    return success_response(item.to_dict())


@bp.route("/api/restaurants/<restaurant_id>/menu-items", methods=["GET"])
@require_roles("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
def list_menu_items(restaurant_id):
    get_restaurant_or_404(restaurant_id)

    is_listed_filter = request.args.get("is_listed")
    limit = request.args.get("limit", 10, type=int)
    offset = request.args.get("offset", 0, type=int)

    if limit < 1 or limit > 100:
        raise_error(ERR_VALIDATION, "limit must be between 1 and 100.")
    if offset < 0:
        raise_error(ERR_VALIDATION, "offset must be >= 0.")

    items = sorted(
        [i for i in db.menu_items.values() if i.restaurant_id == restaurant_id],
        key=lambda i: i.created_at,
    )

    if is_listed_filter is not None:
        val = is_listed_filter.lower() == "true"
        items = [i for i in items if i.is_listed == val]

    total_count = len(items)
    page = items[offset:offset + limit]
    return success_response(
        [i.to_dict() for i in page],
        pagination={
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + limit < total_count,
        },
    )
