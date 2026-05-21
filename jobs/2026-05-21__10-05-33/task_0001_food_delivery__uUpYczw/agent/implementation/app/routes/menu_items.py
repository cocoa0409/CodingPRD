"""Menu-item endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from .. import cascade
from ..auth import require_role
from ..envelope import envelope_array, envelope_object, expect_json_body
from ..errors import ApiError
from ..ids import new_uuid
from ..pagination import apply as apply_pagination, parse as parse_pagination
from ..store import get_clock, get_store
from ..validators import opt_bool, req_int, req_str

bp = Blueprint("menu_items", __name__, url_prefix="/api")


def _ensure_restaurant(store, rid):
    rec = store.restaurants.get(rid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", f"Restaurant {rid} not found")
    return rec


def _ensure_menu_item(store, mid):
    rec = store.menu_items.get(mid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", f"Menu item {mid} not found")
    return rec


@bp.post("/restaurants/<rid>/menu-items")
def create_menu_item(rid):
    uid, role = require_role({"Restaurant", "PlatformAdmin"})
    body = expect_json_body()
    store = get_store()
    clock = get_clock()
    with store.lock:
        restaurant = _ensure_restaurant(store, rid)
        if role == "Restaurant" and uid != restaurant["id"]:
            raise ApiError("ERR_FORBIDDEN", "Restaurant may only modify own menu")

        name = req_str(body, "name").strip()
        if not name:
            raise ApiError("ERR_VALIDATION", "name required")
        price = req_int(body, "price_cents")
        if not 1 <= price <= 1_000_000:
            raise ApiError("ERR_VALIDATION", "price_cents out of range")
        listed = opt_bool(body, "is_listed")
        if listed is None:
            listed = True

        now = clock.now_iso()
        rec = {
            "id": new_uuid(),
            "restaurant_id": restaurant["id"],
            "name": name,
            "price_cents": price,
            "is_listed": listed,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.menu_items[rec["id"]] = rec
    return envelope_object(rec, status=201)


@bp.patch("/menu-items/<mid>")
def patch_menu_item(mid):
    uid, role = require_role({"Restaurant", "PlatformAdmin"})
    body = expect_json_body()
    store = get_store()
    clock = get_clock()
    with store.lock:
        item = _ensure_menu_item(store, mid)
        restaurant = store.restaurants[item["restaurant_id"]]
        if role == "Restaurant" and uid != restaurant["id"]:
            raise ApiError("ERR_FORBIDDEN", "Restaurant may only modify own menu")

        if "version" in body and body["version"] is not None:
            if body["version"] != item["version"]:
                raise ApiError("ERR_VERSION_CONFLICT", "menu_item version mismatch")

        if "price_cents" in body and body["price_cents"] is not None:
            p = body["price_cents"]
            if isinstance(p, bool) or not isinstance(p, int):
                raise ApiError("ERR_VALIDATION", "price_cents must be int")
            if not 1 <= p <= 1_000_000:
                raise ApiError("ERR_VALIDATION", "price_cents out of range")
            item["price_cents"] = p
        if "is_listed" in body:
            v = body["is_listed"]
            if not isinstance(v, bool):
                raise ApiError("ERR_VALIDATION", "is_listed must be bool")
            item["is_listed"] = v

        cascade.touch(item, clock)
    return envelope_object(item)


@bp.get("/restaurants/<rid>/menu-items")
def list_menu_items(rid):
    require_role({"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"})
    limit, offset = parse_pagination()
    is_listed_q = request.args.get("is_listed")
    store = get_store()
    with store.lock:
        _ensure_restaurant(store, rid)
        items = [m for m in store.menu_items.values() if m["restaurant_id"] == rid]
        if is_listed_q is not None:
            if is_listed_q.lower() not in {"true", "false"}:
                raise ApiError("ERR_VALIDATION", "is_listed must be boolean")
            wanted = is_listed_q.lower() == "true"
            items = [m for m in items if m["is_listed"] == wanted]
        window, total = apply_pagination(items, limit, offset)
    return envelope_array(window, limit=limit, offset=offset, total_count=total)
