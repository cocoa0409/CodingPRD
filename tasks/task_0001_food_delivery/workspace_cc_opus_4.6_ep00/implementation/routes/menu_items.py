from flask import Blueprint, request
from store import store
from models import make_versioned, touch, serialize
from middleware import check_role_permission
from response import success_response
from pagination import get_pagination_params, paginate
from errors import raise_error, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_VALIDATION, ERR_VERSION_CONFLICT

bp = Blueprint("menu_items", __name__)


@bp.route("/api/restaurants/<restaurant_id>/menu-items", methods=["POST"])
def create_menu_item(restaurant_id):
    check_role_permission({"Restaurant", "PlatformAdmin"})
    restaurant = store.restaurants.get(restaurant_id)
    if not restaurant:
        raise_error(ERR_NOT_FOUND, "Restaurant not found")

    if request.user_role == "Restaurant" and request.user_id != restaurant_id:
        raise_error(ERR_FORBIDDEN, "Cannot create menu items for another restaurant")

    data = request.get_json(force=True, silent=True) or {}
    name = data.get("name")
    if not name or not isinstance(name, str) or len(name.strip()) == 0:
        raise_error(ERR_VALIDATION, "name is required")

    price_cents = data.get("price_cents")
    if price_cents is None or not isinstance(price_cents, int):
        raise_error(ERR_VALIDATION, "price_cents is required and must be an integer")
    if price_cents < 1 or price_cents > 1000000:
        raise_error(ERR_VALIDATION, "price_cents must be between 1 and 1000000")

    is_listed = data.get("is_listed", True)

    item = make_versioned({
        "restaurant_id": restaurant_id,
        "name": name,
        "price_cents": price_cents,
        "is_listed": is_listed,
    })
    store.menu_items[item["id"]] = item
    return success_response(serialize(item), 201)


@bp.route("/api/menu-items/<item_id>", methods=["PATCH"])
def update_menu_item(item_id):
    check_role_permission({"Restaurant", "PlatformAdmin"})
    item = store.menu_items.get(item_id)
    if not item:
        raise_error(ERR_NOT_FOUND, "Menu item not found")

    if request.user_role == "Restaurant" and request.user_id != item["restaurant_id"]:
        raise_error(ERR_FORBIDDEN, "Cannot update another restaurant's menu item")

    data = request.get_json(force=True, silent=True) or {}

    if "version" in data and data["version"] is not None:
        if data["version"] != item["version"]:
            raise_error(ERR_VERSION_CONFLICT, "Version conflict")

    if "price_cents" in data:
        pc = data["price_cents"]
        if not isinstance(pc, int) or pc < 1 or pc > 1000000:
            raise_error(ERR_VALIDATION, "price_cents must be integer between 1 and 1000000")
        item["price_cents"] = pc

    if "is_listed" in data:
        item["is_listed"] = bool(data["is_listed"])

    touch(item)
    return success_response(serialize(item))


@bp.route("/api/restaurants/<restaurant_id>/menu-items", methods=["GET"])
def list_menu_items(restaurant_id):
    check_role_permission({"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"})
    restaurant = store.restaurants.get(restaurant_id)
    if not restaurant:
        raise_error(ERR_NOT_FOUND, "Restaurant not found")

    limit, offset = get_pagination_params()
    items = sorted(
        [i for i in store.menu_items.values() if i["restaurant_id"] == restaurant_id],
        key=lambda i: i["created_at"],
    )

    is_listed_filter = request.args.get("is_listed")
    if is_listed_filter is not None:
        val = is_listed_filter.lower() == "true"
        items = [i for i in items if i["is_listed"] == val]

    page, pagination_meta = paginate(items, limit, offset)
    return success_response([serialize(i) for i in page], 200, pagination_meta)
