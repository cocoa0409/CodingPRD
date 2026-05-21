"""Menu item endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from auth import require_roles
from common import get_json_body, paginate, parse_pagination, require_int, require_str
from envelope import success
from errors import ApiError
from serializers import serialize_menu_item
import store
from store import gen_id, iso_z, lock, now


bp = Blueprint("menu_items", __name__, url_prefix="/api")


def _find_restaurant(rid: str) -> dict:
    r = store.restaurants.get(rid)
    if not r:
        raise ApiError("ERR_NOT_FOUND", "Restaurant not found.")
    return r


def _find_menu_item(mid: str) -> dict:
    m = store.menu_items.get(mid)
    if not m:
        raise ApiError("ERR_NOT_FOUND", "Menu item not found.")
    return m


def _validate_price(price: int) -> None:
    if price < 1 or price > 1_000_000:
        raise ApiError("ERR_VALIDATION", "price_cents must be between 1 and 1000000.")


@bp.post("/restaurants/<rid>/menu-items")
@require_roles("Restaurant", "PlatformAdmin")
def create_menu_item(rid: str):
    r = _find_restaurant(rid)
    if g.role == "Restaurant" and g.user_id != r["id"]:
        raise ApiError("ERR_FORBIDDEN", "Restaurant identity mismatch.")
    body = get_json_body()
    name = require_str(body, "name", max_len=200)
    price = require_int(body, "price_cents")
    _validate_price(price)
    is_listed = body.get("is_listed", True)
    if not isinstance(is_listed, bool):
        raise ApiError("ERR_VALIDATION", "is_listed must be boolean.")

    with lock():
        t = now()
        mid = gen_id()
        rec = {
            "id": mid,
            "restaurant_id": r["id"],
            "name": name,
            "price_cents": price,
            "is_listed": is_listed,
            "created_at": iso_z(t),
            "updated_at": iso_z(t),
            "version": 1,
        }
        store.menu_items[mid] = rec
    return success(serialize_menu_item(rec), status=201)


@bp.patch("/menu-items/<mid>")
@require_roles("Restaurant", "PlatformAdmin")
def patch_menu_item(mid: str):
    m = _find_menu_item(mid)
    if g.role == "Restaurant" and g.user_id != m["restaurant_id"]:
        raise ApiError("ERR_FORBIDDEN", "Restaurant identity mismatch.")
    body = get_json_body()

    changes = {}
    if "price_cents" in body:
        p = body["price_cents"]
        if isinstance(p, bool) or not isinstance(p, int):
            raise ApiError("ERR_VALIDATION", "price_cents must be an integer.")
        _validate_price(p)
        changes["price_cents"] = p
    if "is_listed" in body:
        il = body["is_listed"]
        if not isinstance(il, bool):
            raise ApiError("ERR_VALIDATION", "is_listed must be boolean.")
        changes["is_listed"] = il
    if "name" in body:
        raise ApiError("ERR_VALIDATION", "menu item name is immutable.")

    if "version" in body and body["version"] is not None and body["version"] != m["version"]:
        raise ApiError("ERR_VERSION_CONFLICT", "Resource version mismatch.")

    if not changes:
        return success(serialize_menu_item(m))

    with lock():
        m.update(changes)
        m["updated_at"] = iso_z(now())
        m["version"] += 1
    return success(serialize_menu_item(m))


@bp.get("/restaurants/<rid>/menu-items")
@require_roles("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
def list_menu_items(rid: str):
    _find_restaurant(rid)
    is_listed_raw = request.args.get("is_listed")
    limit, offset = parse_pagination()
    items = [m for m in store.menu_items.values() if m["restaurant_id"] == rid]
    if is_listed_raw is not None:
        if is_listed_raw.lower() in ("true", "1"):
            wanted = True
        elif is_listed_raw.lower() in ("false", "0"):
            wanted = False
        else:
            raise ApiError("ERR_VALIDATION", "is_listed must be true or false.")
        items = [m for m in items if m["is_listed"] == wanted]
    items.sort(key=lambda m: m["created_at"])
    window, meta = paginate(items, limit, offset)
    return success([serialize_menu_item(m) for m in window], list_meta=meta)
