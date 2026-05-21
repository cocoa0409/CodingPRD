"""Menu item endpoints."""

from __future__ import annotations

from flask import request

from auth import require_role
from envelope import list_success, success
from errors import APIError
from resources import check_version, make_versioned, touch
from store import STORE
from validation import get_body, parse_pagination, require_int, require_str


def _serialize(m: dict) -> dict:
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


def register(app):
    @app.post("/api/restaurants/<rid>/menu-items")
    def create_menu_item(rid: str):
        user_id, role = require_role({"Restaurant", "PlatformAdmin"})
        body = get_body()
        with STORE.lock:
            r = STORE.restaurants.get(rid)
            if r is None:
                raise APIError("ERR_NOT_FOUND", "No such restaurant.")
            if role == "Restaurant" and user_id != r["id"]:
                raise APIError("ERR_FORBIDDEN")
            name = require_str(body, "name", min_length=1, max_length=200)
            price_cents = require_int(body, "price_cents", minimum=1, maximum=1_000_000)
            is_listed = body.get("is_listed", True)
            if not isinstance(is_listed, bool):
                raise APIError("ERR_VALIDATION", "is_listed must be boolean.")
            item = make_versioned({
                "restaurant_id": rid,
                "name": name,
                "price_cents": price_cents,
                "is_listed": is_listed,
            })
            STORE.menu_items[item["id"]] = item
            return success(_serialize(item), status=201)

    @app.patch("/api/menu-items/<mid>")
    def patch_menu_item(mid: str):
        user_id, role = require_role({"Restaurant", "PlatformAdmin"})
        body = get_body()
        with STORE.lock:
            item = STORE.menu_items.get(mid)
            if item is None:
                raise APIError("ERR_NOT_FOUND", "No such menu item.")
            if role == "Restaurant" and user_id != item["restaurant_id"]:
                raise APIError("ERR_FORBIDDEN")
            allowed = {"price_cents", "is_listed", "version"}
            unknown = set(body.keys()) - allowed
            if unknown:
                raise APIError("ERR_VALIDATION", f"Unknown/immutable field(s): {sorted(unknown)}")
            check_version(item, body.get("version"))
            if "price_cents" in body:
                p = body["price_cents"]
                if not isinstance(p, int) or isinstance(p, bool) or p < 1 or p > 1_000_000:
                    raise APIError("ERR_VALIDATION", "price_cents out of range.")
                item["price_cents"] = p
            if "is_listed" in body:
                if not isinstance(body["is_listed"], bool):
                    raise APIError("ERR_VALIDATION", "is_listed must be boolean.")
                item["is_listed"] = body["is_listed"]
            touch(item)
            return success(_serialize(item))

    @app.get("/api/restaurants/<rid>/menu-items")
    def list_menu_items(rid: str):
        require_role({"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"})
        limit, offset = parse_pagination()
        with STORE.lock:
            r = STORE.restaurants.get(rid)
            if r is None:
                raise APIError("ERR_NOT_FOUND", "No such restaurant.")
            items = [m for m in STORE.menu_items.values() if m["restaurant_id"] == rid]
            is_listed_q = request.args.get("is_listed")
            if is_listed_q is not None:
                if is_listed_q.lower() not in ("true", "false"):
                    raise APIError("ERR_VALIDATION", "is_listed must be true/false.")
                want = is_listed_q.lower() == "true"
                items = [m for m in items if m["is_listed"] == want]
            items.sort(key=lambda m: m["created_at"])
            page = items[offset:offset + limit]
            return list_success([_serialize(m) for m in page], limit, offset, len(items))
