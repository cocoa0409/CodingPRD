"""Menu-item CRUD endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_role
from ..envelope import success_list, success_object
from ..errors import ApiError
from ..ids import new_uuid
from ..pagination import page_slice, parse_pagination
from ..serializers import menu_item_out
from ..validation import ensure_dict, require_int, require_str
from ..version_ctl import bump, check_version


bp = Blueprint("menu_items", __name__, url_prefix="/api")


@bp.post("/restaurants/<rid>/menu-items")
def create_menu_item(rid: str):
    require_role("Restaurant", "PlatformAdmin")
    store = g.store
    with store.lock:
        r = store.restaurants.get(rid)
        if not r:
            raise ApiError("ERR_NOT_FOUND")
        if g.user_role == "Restaurant" and g.user_id != rid:
            raise ApiError("ERR_FORBIDDEN")
        body = ensure_dict(request.get_json(silent=True) or {})
        name = require_str(body, "name", max_len=120)
        price = require_int(body, "price_cents", min_val=1, max_val=1_000_000)
        is_listed = body.get("is_listed", True)
        if not isinstance(is_listed, bool):
            raise ApiError("ERR_VALIDATION", "is_listed must be boolean")
        mid = new_uuid()
        now = store.now_iso()
        m = {
            "id": mid,
            "restaurant_id": rid,
            "name": name,
            "price_cents": price,
            "is_listed": is_listed,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.menu_items[mid] = m
        return success_object(store.clock, menu_item_out(m), status=201)


@bp.patch("/menu-items/<mid>")
def update_menu_item(mid: str):
    require_role("Restaurant", "PlatformAdmin")
    store = g.store
    body = ensure_dict(request.get_json(silent=True) or {})
    with store.lock:
        m = store.menu_items.get(mid)
        if not m:
            raise ApiError("ERR_NOT_FOUND")
        if g.user_role == "Restaurant" and g.user_id != m["restaurant_id"]:
            raise ApiError("ERR_FORBIDDEN")
        check_version(m, body)
        if "price_cents" in body:
            m["price_cents"] = require_int(body, "price_cents", min_val=1, max_val=1_000_000)
        if "is_listed" in body:
            v = body["is_listed"]
            if not isinstance(v, bool):
                raise ApiError("ERR_VALIDATION", "is_listed must be boolean")
            m["is_listed"] = v
        bump(m, store.now_iso())
        return success_object(store.clock, menu_item_out(m))


@bp.get("/restaurants/<rid>/menu-items")
def list_menu_items(rid: str):
    require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    store = g.store
    if rid not in store.restaurants:
        raise ApiError("ERR_NOT_FOUND")
    limit, offset = parse_pagination()
    is_listed_q = request.args.get("is_listed")
    rows = [m for m in store.menu_items.values() if m["restaurant_id"] == rid]
    if is_listed_q is not None:
        if is_listed_q.lower() in ("true", "1"):
            want = True
        elif is_listed_q.lower() in ("false", "0"):
            want = False
        else:
            raise ApiError("ERR_VALIDATION", "is_listed filter must be boolean")
        rows = [m for m in rows if m["is_listed"] == want]
    page, total = page_slice(rows, limit=limit, offset=offset)
    return success_list(
        store.clock,
        [menu_item_out(m) for m in page],
        limit=limit,
        offset=offset,
        total_count=total,
    )
