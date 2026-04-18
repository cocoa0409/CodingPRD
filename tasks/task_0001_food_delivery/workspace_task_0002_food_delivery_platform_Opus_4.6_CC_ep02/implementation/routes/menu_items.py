from flask import Blueprint, request
from auth import require_roles, check_ownership
from errors import APIError
from models import restaurants, menu_items, versioned_resource_base, touch, check_version
from response_envelope import success_response
from pagination import parse_pagination_params, paginate

bp = Blueprint("menu_items", __name__)


def menu_item_dict(m):
    return {
        "id": m["id"],
        "restaurant_id": m["restaurant_id"],
        "name": m["name"],
        "price_cents": m["price_cents"],
        "is_listed": m["is_listed"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


@bp.route("/api/restaurants/<restaurant_id>/menu-items", methods=["POST"])
@require_roles("Restaurant", "PlatformAdmin")
def create_menu_item(restaurant_id):
    r = restaurants.get(restaurant_id)
    if not r:
        raise APIError("ERR_NOT_FOUND", "Restaurant not found")

    check_ownership(restaurant_id, request.user_id, request.user_role, ["Restaurant"])

    data = request.get_json(force=True, silent=True) or {}

    name = data.get("name")
    if not name or not isinstance(name, str) or len(name.strip()) == 0:
        raise APIError("ERR_VALIDATION", "name is required")

    price_cents = data.get("price_cents")
    if price_cents is None or not isinstance(price_cents, int):
        raise APIError("ERR_VALIDATION", "price_cents must be an integer")
    if price_cents < 1 or price_cents > 1000000:
        raise APIError("ERR_VALIDATION", "price_cents must be between 1 and 1000000")

    is_listed = data.get("is_listed", True)

    m = versioned_resource_base()
    m.update({
        "restaurant_id": restaurant_id,
        "name": name,
        "price_cents": price_cents,
        "is_listed": is_listed,
    })

    menu_items[m["id"]] = m
    return success_response(menu_item_dict(m), 201)


@bp.route("/api/menu-items/<item_id>", methods=["PATCH"])
@require_roles("Restaurant", "PlatformAdmin")
def update_menu_item(item_id):
    m = menu_items.get(item_id)
    if not m:
        raise APIError("ERR_NOT_FOUND", "Menu item not found")

    check_ownership(m["restaurant_id"], request.user_id, request.user_role, ["Restaurant"])

    data = request.get_json(force=True, silent=True) or {}
    check_version(m, data.get("version"))

    if "price_cents" in data:
        price_cents = data["price_cents"]
        if not isinstance(price_cents, int):
            raise APIError("ERR_VALIDATION", "price_cents must be an integer")
        if price_cents < 1 or price_cents > 1000000:
            raise APIError("ERR_VALIDATION", "price_cents must be between 1 and 1000000")
        m["price_cents"] = price_cents

    if "is_listed" in data:
        m["is_listed"] = bool(data["is_listed"])

    touch(m)
    return success_response(menu_item_dict(m))


@bp.route("/api/restaurants/<restaurant_id>/menu-items", methods=["GET"])
@require_roles("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
def list_menu_items(restaurant_id):
    r = restaurants.get(restaurant_id)
    if not r:
        raise APIError("ERR_NOT_FOUND", "Restaurant not found")

    limit, offset = parse_pagination_params(request.args)
    is_listed_filter = request.args.get("is_listed")

    items = sorted(
        [m for m in menu_items.values() if m["restaurant_id"] == restaurant_id],
        key=lambda x: x["created_at"]
    )

    if is_listed_filter is not None:
        is_listed_val = is_listed_filter.lower() == "true"
        items = [m for m in items if m["is_listed"] == is_listed_val]

    page, pagination = paginate(items, limit, offset)
    return success_response([menu_item_dict(m) for m in page], 200, "array", pagination)
