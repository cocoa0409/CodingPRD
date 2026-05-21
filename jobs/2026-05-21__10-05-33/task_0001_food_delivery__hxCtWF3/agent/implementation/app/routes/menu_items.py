"""Menu item endpoints."""
from flask import request

from ..auth import parse_headers, require_role
from ..envelope import success
from ..errors import fail
from ..pagination import parse_pagination, window
from ..resource import stamp_new, bump, check_occ
from ..server import store


def register(app, prefix):
    app.add_url_rule("/api/restaurants/<rid>/menu-items", endpoint=f"{prefix}.create", view_func=create, methods=["POST"])
    app.add_url_rule("/api/restaurants/<rid>/menu-items", endpoint=f"{prefix}.list", view_func=list_items, methods=["GET"])
    app.add_url_rule("/api/menu-items/<mid>", endpoint=f"{prefix}.update", view_func=update, methods=["PATCH"])


def _restaurant(rid):
    r = store.restaurants.get(rid)
    if not r:
        raise fail("ERR_NOT_FOUND")
    return r


def create(rid):
    user_id, role = parse_headers()
    require_role("Restaurant", "PlatformAdmin")
    r = _restaurant(rid)
    if role == "Restaurant" and user_id != r["id"]:
        raise fail("ERR_FORBIDDEN")
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    price = body.get("price_cents")
    if not isinstance(name, str) or not name.strip():
        raise fail("ERR_VALIDATION", "name required")
    if not isinstance(price, int) or isinstance(price, bool) or price < 1 or price > 1_000_000:
        raise fail("ERR_VALIDATION", "price_cents must be int in [1, 1_000_000]")
    is_listed = body.get("is_listed", True)
    if not isinstance(is_listed, bool):
        raise fail("ERR_VALIDATION", "is_listed must be boolean")
    rec = stamp_new()
    rec.update({
        "restaurant_id": r["id"],
        "name": name,
        "price_cents": price,
        "is_listed": is_listed,
    })
    store.menu_items[rec["id"]] = rec
    return success(rec, status=201)


def list_items(rid):
    parse_headers()
    require_role("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
    _restaurant(rid)
    limit, offset = parse_pagination()
    filt = request.args.get("is_listed")
    rows = [m for m in store.menu_items.values() if m["restaurant_id"] == rid]
    if filt is not None:
        want = filt.lower() == "true"
        rows = [m for m in rows if m["is_listed"] == want]
    rows.sort(key=lambda m: m["created_at"])
    page, meta = window(rows, limit, offset)
    return success(page, page=meta, response_type="array")


def update(mid):
    user_id, role = parse_headers()
    require_role("Restaurant", "PlatformAdmin")
    m = store.menu_items.get(mid)
    if not m:
        raise fail("ERR_NOT_FOUND")
    if role == "Restaurant" and user_id != m["restaurant_id"]:
        raise fail("ERR_FORBIDDEN")
    body = request.get_json(silent=True) or {}
    check_occ(m, body)
    if "price_cents" in body:
        p = body["price_cents"]
        if not isinstance(p, int) or isinstance(p, bool) or p < 1 or p > 1_000_000:
            raise fail("ERR_VALIDATION", "price_cents must be int in [1, 1_000_000]")
        m["price_cents"] = p
    if "is_listed" in body:
        if not isinstance(body["is_listed"], bool):
            raise fail("ERR_VALIDATION", "is_listed must be boolean")
        m["is_listed"] = body["is_listed"]
    bump(m)
    return success(m)
