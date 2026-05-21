from flask import Blueprint, request

from ..auth import require_role
from ..envelope import success, created, list_ok
from ..errors import err
from ..pagination import parse_limit_offset, paginate
from ..repository import base_versioned, touch, check_version, body_or_empty
from ..store import store

bp = Blueprint("menu_items", __name__)


def _view(m):
    return {k: m[k] for k in ("id", "restaurant_id", "name", "price_cents", "is_listed",
                              "created_at", "updated_at", "version")}


@bp.post("/api/restaurants/<rid>/menu-items")
def create_menu_item(rid):
    uid, role = require_role("Restaurant", "PlatformAdmin")
    r = store.restaurants.get(rid)
    if r is None:
        raise err("ERR_NOT_FOUND", "restaurant not found")
    if role == "Restaurant" and r["id"] != uid:
        raise err("ERR_FORBIDDEN", "not the owning restaurant")
    body = body_or_empty()
    name = body.get("name")
    price_cents = body.get("price_cents")
    is_listed = body.get("is_listed", True)
    if not isinstance(name, str) or not name.strip():
        raise err("ERR_VALIDATION", "name required")
    if not isinstance(price_cents, int) or isinstance(price_cents, bool):
        raise err("ERR_VALIDATION", "price_cents must be integer")
    if price_cents < 1 or price_cents > 1_000_000:
        raise err("ERR_VALIDATION", "price_cents out of range")
    if not isinstance(is_listed, bool):
        raise err("ERR_VALIDATION", "is_listed must be boolean")
    m = base_versioned()
    m.update({
        "restaurant_id": rid,
        "name": name.strip(),
        "price_cents": price_cents,
        "is_listed": is_listed,
    })
    store.menu_items[m["id"]] = m
    return created(_view(m))


@bp.patch("/api/menu-items/<mid>")
def patch_menu_item(mid):
    uid, role = require_role("Restaurant", "PlatformAdmin")
    m = store.menu_items.get(mid)
    if m is None:
        raise err("ERR_NOT_FOUND", "menu item not found")
    if role == "Restaurant" and m["restaurant_id"] != uid:
        raise err("ERR_FORBIDDEN", "not the owning restaurant")
    body = body_or_empty()
    if "price_cents" in body:
        v = body["price_cents"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 1 or v > 1_000_000:
            raise err("ERR_VALIDATION", "price_cents invalid")
    if "is_listed" in body and not isinstance(body["is_listed"], bool):
        raise err("ERR_VALIDATION", "is_listed must be boolean")
    check_version(m, body)
    if "price_cents" in body:
        m["price_cents"] = body["price_cents"]
    if "is_listed" in body:
        m["is_listed"] = body["is_listed"]
    touch(m)
    return success(_view(m))


@bp.get("/api/restaurants/<rid>/menu-items")
def list_menu_items(rid):
    require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    if rid not in store.restaurants:
        raise err("ERR_NOT_FOUND", "restaurant not found")
    limit, offset = parse_limit_offset()
    is_listed = request.args.get("is_listed")
    items = [m for m in store.menu_items.values() if m["restaurant_id"] == rid]
    if is_listed is not None:
        if is_listed.lower() in ("true", "1"):
            items = [m for m in items if m["is_listed"]]
        elif is_listed.lower() in ("false", "0"):
            items = [m for m in items if not m["is_listed"]]
        else:
            raise err("ERR_VALIDATION", "is_listed must be boolean")
    items.sort(key=lambda x: x["created_at"])
    window, total = paginate(items, limit, offset)
    return list_ok([_view(x) for x in window], limit, offset, total)
