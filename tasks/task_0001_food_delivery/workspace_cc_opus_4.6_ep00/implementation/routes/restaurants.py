from flask import Blueprint, request
from store import store
from models import make_versioned, touch, serialize
from middleware import require_roles, check_role_permission
from response import success_response
from pagination import get_pagination_params, paginate
from errors import raise_error, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_VALIDATION, ERR_VERSION_CONFLICT

bp = Blueprint("restaurants", __name__)


@bp.route("/api/restaurants", methods=["POST"])
def create_restaurant():
    check_role_permission({"PlatformAdmin"})
    data = request.get_json(force=True, silent=True) or {}

    name = data.get("name")
    if not name or not isinstance(name, str) or len(name.strip()) == 0 or len(name) > 120:
        raise_error(ERR_VALIDATION, "name is required and must be 1-120 characters")

    for r in store.restaurants.values():
        if r["name"] == name and r["status"] != "CLOSED":
            raise_error(ERR_VALIDATION, "Restaurant name must be unique among active restaurants")

    address = data.get("address")
    if not address or not isinstance(address, str):
        raise_error(ERR_VALIDATION, "address is required")

    lat = data.get("lat")
    lng = data.get("lng")
    if lat is None or lng is None:
        raise_error(ERR_VALIDATION, "lat and lng are required")
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        raise_error(ERR_VALIDATION, "lat and lng must be numbers")

    commission_rate_override = data.get("commission_rate_override")
    if commission_rate_override is not None:
        if not isinstance(commission_rate_override, (int, float)):
            raise_error(ERR_VALIDATION, "commission_rate_override must be a number")
        if commission_rate_override < 0.05 or commission_rate_override > 0.35:
            raise_error(ERR_VALIDATION, "commission_rate_override must be in [0.05, 0.35]")

    restaurant = make_versioned({
        "name": name,
        "address": address,
        "lat": lat,
        "lng": lng,
        "status": "PENDING_APPROVAL",
        "commission_rate_override": commission_rate_override,
        "pending_settlement_cents": 0,
    })
    store.restaurants[restaurant["id"]] = restaurant
    return success_response(serialize(restaurant), 201)


@bp.route("/api/restaurants", methods=["GET"])
def list_restaurants():
    check_role_permission({"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"})
    status_filter = request.args.get("status")
    limit, offset = get_pagination_params()

    items = sorted(store.restaurants.values(), key=lambda r: r["created_at"])
    if status_filter:
        items = [r for r in items if r["status"] == status_filter]

    page, pagination_meta = paginate(items, limit, offset)
    return success_response([serialize(r) for r in page], 200, pagination_meta)


@bp.route("/api/restaurants/<restaurant_id>", methods=["GET"])
def get_restaurant(restaurant_id):
    check_role_permission({"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"})
    restaurant = store.restaurants.get(restaurant_id)
    if not restaurant:
        raise_error(ERR_NOT_FOUND, "Restaurant not found")
    return success_response(serialize(restaurant))


@bp.route("/api/restaurants/<restaurant_id>", methods=["PATCH"])
def update_restaurant(restaurant_id):
    check_role_permission({"PlatformAdmin", "Restaurant"})
    restaurant = store.restaurants.get(restaurant_id)
    if not restaurant:
        raise_error(ERR_NOT_FOUND, "Restaurant not found")

    if request.user_role == "Restaurant" and request.user_id != restaurant_id:
        raise_error(ERR_FORBIDDEN, "Cannot update another restaurant's profile")

    data = request.get_json(force=True, silent=True) or {}

    if "version" in data and data["version"] is not None:
        if data["version"] != restaurant["version"]:
            raise_error(ERR_VERSION_CONFLICT, "Version conflict")

    if "name" in data:
        raise_error(ERR_VALIDATION, "name is immutable after creation")

    if "address" in data:
        restaurant["address"] = data["address"]
    if "lat" in data:
        restaurant["lat"] = data["lat"]
    if "lng" in data:
        restaurant["lng"] = data["lng"]
    if "commission_rate_override" in data:
        cro = data["commission_rate_override"]
        if cro is not None:
            if not isinstance(cro, (int, float)):
                raise_error(ERR_VALIDATION, "commission_rate_override must be a number")
            if cro < 0.05 or cro > 0.35:
                raise_error(ERR_VALIDATION, "commission_rate_override must be in [0.05, 0.35]")
        restaurant["commission_rate_override"] = cro

    touch(restaurant)
    return success_response(serialize(restaurant))


@bp.route("/api/restaurants/<restaurant_id>/approve", methods=["POST"])
def approve_restaurant(restaurant_id):
    check_role_permission({"PlatformAdmin"})
    restaurant = store.restaurants.get(restaurant_id)
    if not restaurant:
        raise_error(ERR_NOT_FOUND, "Restaurant not found")
    if restaurant["status"] != "PENDING_APPROVAL":
        raise_error(ERR_INVALID_STATE, "Restaurant must be PENDING_APPROVAL to approve")
    restaurant["status"] = "ACTIVE"
    touch(restaurant)
    return success_response(serialize(restaurant))


@bp.route("/api/restaurants/<restaurant_id>/suspend", methods=["POST"])
def suspend_restaurant(restaurant_id):
    check_role_permission({"PlatformAdmin"})
    restaurant = store.restaurants.get(restaurant_id)
    if not restaurant:
        raise_error(ERR_NOT_FOUND, "Restaurant not found")
    if restaurant["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Restaurant must be ACTIVE to suspend")

    restaurant["status"] = "SUSPENDED"
    touch(restaurant)

    for order in store.orders.values():
        if order["restaurant_id"] == restaurant_id and order["status"] == "PLACED":
            order["status"] = "CANCELLED"
            if order["payment_status"] in ("UNPAID", "AUTHORIZED"):
                order["payment_status"] = "VOIDED"
            touch(order)

    return success_response(serialize(restaurant))


@bp.route("/api/restaurants/<restaurant_id>/reinstate", methods=["POST"])
def reinstate_restaurant(restaurant_id):
    check_role_permission({"PlatformAdmin"})
    restaurant = store.restaurants.get(restaurant_id)
    if not restaurant:
        raise_error(ERR_NOT_FOUND, "Restaurant not found")
    if restaurant["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_STATE, "Restaurant must be SUSPENDED to reinstate")
    restaurant["status"] = "ACTIVE"
    touch(restaurant)
    return success_response(serialize(restaurant))


@bp.route("/api/restaurants/<restaurant_id>/settle", methods=["POST"])
def settle_restaurant(restaurant_id):
    check_role_permission({"PlatformAdmin"})
    restaurant = store.restaurants.get(restaurant_id)
    if not restaurant:
        raise_error(ERR_NOT_FOUND, "Restaurant not found")
    restaurant["pending_settlement_cents"] = 0
    touch(restaurant)
    return success_response(serialize(restaurant))
